#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金溢价监控系统（修正版）
功能：实时监控513100和159632的溢价，基于实时价格/同日期单位净值计算
公式：溢价率 = (实时价格 ÷ 同日期单位净值 - 1) × 100%
触发：当513100溢价 - 159632溢价 < 2.8%时发送飞书通知
数据源：新浪财经（实时价格）+ 天天基金网（同日期单位净值）
作者：基金监控系统
"""

import requests
import json
import os
import sys
import time
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# ==================== 配置区域 ====================
# 监控的基金代码和名称
FUND_CODES = {
    '513100': '国泰纳斯达克100(QDII-ETF)',
    '159632': '华安纳斯达克100ETF(QDII)'
}

# 交易所前缀映射
EXCHANGE_PREFIX = {
    '513100': 'sh',  # 上海交易所
    '159632': 'sz'   # 深圳交易所
}

# 触发阈值：513100溢价 - 159632溢价 < 此值时通知
THRESHOLD = 2.8  # 单位：百分比（%）

# 飞书Webhook地址（从环境变量读取，保护隐私）
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
# =================================================

def get_fund_nav_same_date(fund_code: str, target_date: str = None) -> Optional[Dict[str, Any]]:
    """
    从天天基金网获取指定日期的基金净值
    确保两只基金使用同一日期的净值进行比较
    
    返回格式: {
        'date': '2024-05-15',
        'nav': 2.0201,
        'fund_code': '513100',
        'fund_name': '基金名称'
    }
    """
    try:
        # 如果没有指定日期，使用最近一个交易日
        if not target_date:
            # 获取最近交易日（排除周末）
            today = datetime.now()
            if today.weekday() == 5:  # 周六
                target_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
            elif today.weekday() == 6:  # 周日
                target_date = (today - timedelta(days=2)).strftime('%Y-%m-%d')
            else:
                target_date = today.strftime('%Y-%m-%d')
        
        print(f"📅 正在获取 {fund_code} {target_date} 的单位净值...")
        
        # 使用天天基金网的历史净值接口
        url = f"http://fund.eastmoney.com/f10/F10DataApi.aspx"
        
        params = {
            'type': 'lsjz',
            'code': fund_code,
            'page': 1,
            'per': 1,  # 只获取最新一条
            'sdate': '',
            'edate': '',
            'rt': str(time.time())
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'http://fund.eastmoney.com/{fund_code}.html',
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ 获取基金 {fund_code} 净值失败，状态码: {response.status_code}")
            return None
        
        content = response.text
        
        # 解析HTML表格数据
        # 提取表格数据
        table_pattern = r'<table.*?>(.*?)</table>'
        table_match = re.search(table_pattern, content, re.DOTALL)
        
        if not table_match:
            print(f"❌ 未找到基金 {fund_code} 的净值表格")
            return None
        
        table_html = table_match.group(1)
        
        # 使用正则表达式解析表格行
        row_pattern = r'<tr>(.*?)</tr>'
        rows = re.findall(row_pattern, table_html, re.DOTALL)
        
        if len(rows) < 2:  # 第一行是表头
            print(f"❌ 基金 {fund_code} 无净值数据")
            return None
        
        # 获取第一行数据（最新记录）
        latest_row = rows[1]
        
        # 解析单元格
        cell_pattern = r'<td.*?>(.*?)</td>'
        cells = re.findall(cell_pattern, latest_row, re.DOTALL)
        
        if len(cells) < 3:
            print(f"❌ 基金 {fund_code} 数据格式异常")
            return None
        
        # 清理HTML标签
        def clean_html(text):
            return re.sub(r'<.*?>', '', text).strip()
        
        # 解析数据
        nav_date = clean_html(cells[0])  # 日期
        nav_value = clean_html(cells[1])  # 单位净值
        accumulated_nav = clean_html(cells[2])  # 累计净值
        
        # 将中文日期转换为标准格式
        nav_date_std = nav_date.replace('年', '-').replace('月', '-').replace('日', '')
        
        # 转换为浮点数
        try:
            nav_float = float(nav_value)
            accumulated_float = float(accumulated_nav) if accumulated_nav and accumulated_nav != '' else nav_float
            
            return {
                'date': nav_date_std,
                'nav': nav_float,
                'accumulated_nav': accumulated_float,
                'fund_code': fund_code,
                'fund_name': FUND_CODES.get(fund_code, fund_code)
            }
        except ValueError as e:
            print(f"❌ 基金 {fund_code} 净值数据转换失败: {e}")
            print(f"   净值字符串: '{nav_value}', 累计净值: '{accumulated_nav}'")
            return None
            
    except Exception as e:
        print(f"❌ 获取基金 {fund_code} 净值失败: {type(e).__name__}: {e}")
        return None

def get_latest_common_nav():
    """
    获取两只基金同一交易日的最新净值
    策略：取两者都有的最近交易日
    """
    try:
        # 获取513100的最新净值
        print("\n📦 正在获取基金单位净值...")
        fund1_data = get_fund_nav_same_date('513100')
        fund2_data = get_fund_nav_same_date('159632')
        
        if not fund1_data or not fund2_data:
            print("❌ 无法获取两只基金的净值数据")
            return None, None
        
        # 检查日期是否一致
        if fund1_data['date'] != fund2_data['date']:
            print(f"⚠️  净值日期不一致: 513100={fund1_data['date']}, 159632={fund2_data['date']}")
            
            # 策略：使用较早的日期（确保两只基金都有数据）
            date1 = datetime.strptime(fund1_data['date'], '%Y-%m-%d')
            date2 = datetime.strptime(fund2_data['date'], '%Y-%m-%d')
            
            common_date = min(date1, date2).strftime('%Y-%m-%d')
            print(f"📅 使用共同日期: {common_date}")
            
            # 重新获取指定日期的净值
            print(f"🔄 重新获取 {common_date} 的净值数据...")
            fund1_data = get_fund_nav_same_date('513100', common_date)
            fund2_data = get_fund_nav_same_date('159632', common_date)
            
            if not fund1_data or not fund2_data:
                print("❌ 重新获取净值数据失败")
                return None, None
        
        print(f"✅ 净值获取完成，使用日期: {fund1_data['date']}")
        print(f"   513100 净值: {fund1_data['nav']:.4f}")
        print(f"   159632 净值: {fund2_data['nav']:.4f}")
        
        return fund1_data, fund2_data
        
    except Exception as e:
        print(f"❌ 获取共同净值失败: {type(e).__name__}: {e}")
        return None, None

def get_etf_realtime_price(fund_code: str) -> Optional[Dict[str, Any]]:
    """
    从新浪财经获取ETF实时交易价格（股票行情接口）
    注意：使用股票行情接口，而不是基金净值接口
    """
    try:
        # 确定交易所前缀
        exchange_prefix = EXCHANGE_PREFIX.get(fund_code, 'sh')
        stock_code = f"{exchange_prefix}{fund_code}"
        
        url = f"https://hq.sinajs.cn/list={stock_code}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
            'Accept': '*/*',
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ 获取ETF {fund_code} 实时价格失败，HTTP状态码: {response.status_code}")
            return None
        
        response.encoding = 'gbk'
        raw_text = response.text.strip()
        
        if not raw_text.startswith(f'var hq_str_{stock_code}='):
            print(f"❌ ETF {fund_code} 响应格式异常")
            return None
        
        # 提取数据
        data_start = raw_text.find('"')
        data_end = raw_text.rfind('"')
        
        if data_start == -1 or data_end == -1 or data_start >= data_end:
            print(f"❌ ETF {fund_code} 数据解析失败")
            return None
        
        data_str = raw_text[data_start + 1:data_end]
        
        if not data_str or data_str == "":
            print(f"❌ ETF {fund_code} 数据为空")
            return None
        
        fields = data_str.split(',')
        
        if len(fields) < 4:
            print(f"❌ ETF {fund_code} 数据字段不足")
            return None
        
        try:
            # 股票行情接口字段说明（新浪财经）：
            # 0: 股票名称
            # 1: 今日开盘价
            # 2: 昨日收盘价
            # 3: 当前价格（最新价）<- 我们需要这个
            # 4: 今日最高价
            # 5: 今日最低价
            # 6: 竞买价（买一）
            # 7: 竞卖价（卖一）
            # 8: 成交量（股）
            # 9: 成交额（元）
            # 30: 日期
            # 31: 时间
            
            current_price = float(fields[3])
            
            return {
                'price': round(current_price, 4),
                'fund_name': fields[0] if fields[0] else FUND_CODES.get(fund_code, fund_code),
                'update_time': datetime.now().strftime('%H:%M:%S'),
                'data_time': f"{fields[30]} {fields[31]}" if len(fields) > 31 else "N/A",
                'open_price': float(fields[1]) if fields[1] else 0,
                'high_price': float(fields[4]) if fields[4] else 0,
                'low_price': float(fields[5]) if fields[5] else 0,
                'volume': fields[8] if len(fields) > 8 else "0",
                'amount': fields[9] if len(fields) > 9 else "0",
                'status': '正常'
            }
            
        except (ValueError, IndexError) as e:
            print(f"❌ ETF {fund_code} 价格解析错误: {e}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"⏰ 获取ETF {fund_code} 实时价格超时")
        return None
    except Exception as e:
        print(f"❌ 获取ETF {fund_code} 实时价格失败: {type(e).__name__}: {e}")
        return None

def send_feishu_notification(fund1_data: Dict[str, Any], fund2_data: Dict[str, Any], 
                            premium_diff: float) -> bool:
    """
    发送飞书消息通知
    """
    if not FEISHU_WEBHOOK:
        print("❌ 错误：未配置飞书Webhook地址")
        print("💡 请在GitHub仓库的Settings -> Secrets -> Actions中添加FEISHU_WEBHOOK")
        return False
    
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 判断是否触发告警
        is_alert = premium_diff < THRESHOLD
        alert_status = "🚨 **已触发告警**" if is_alert else "✅ **监控正常**"
        
        # 构建消息内容
        message = f"""{alert_status}

⏰ **触发时间**: {current_time}
📡 **数据来源**: 
   实时价格 - 新浪财经股票行情
   单位净值 - 天天基金网（基于同一交易日{fund1_data['nav_date']}）
🔄 **监控频率**: 每3分钟自动检查

📊 **实时行情对比**:

1️⃣ **{fund1_data['fund_code']}** {fund1_data['fund_name']}
   ├─ 实时价格: {fund1_data['price']:.4f} 元
   ├─ 单位净值: {fund1_data['nav']:.4f} 元（{fund1_data['nav_date']}）
   ├─ 溢价率: {fund1_data['premium']:.3f}%
   └─ 更新时间: {fund1_data['update_time']}

2️⃣ **{fund2_data['fund_code']}** {fund2_data['fund_name']}
   ├─ 实时价格: {fund2_data['price']:.4f} 元
   ├─ 单位净值: {fund2_data['nav']:.4f} 元（{fund2_data['nav_date']}）
   ├─ 溢价率: {fund2_data['premium']:.3f}%
   └─ 更新时间: {fund2_data['update_time']}

🎯 **监控结果**:
├─ 溢价差: {premium_diff:.3f}% (513100溢价 - 159632溢价)
├─ 触发阈值: <{THRESHOLD}%
├─ 当前状态: {'已触发告警' if is_alert else '正常'}
└─ 数据时间: {fund1_data['data_time']}

📐 **计算公式**:
溢价率 = (实时价格 ÷ 单位净值 - 1) × 100%
溢价差 = 513100溢价率 - 159632溢价率

⚠️ **重要说明**:
1. 单位净值使用同一交易日数据，确保比较公平
2. 实时价格为当前市场交易价格
3. 溢价率仅供参考，实际套利需考虑交易成本
4. 投资有风险，决策需谨慎"""

        # 飞书Webhook请求数据
        data = {
            "msg_type": "text",
            "content": {
                "text": message
            }
        }
        
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }
        
        response = requests.post(
            FEISHU_WEBHOOK,
            headers=headers,
            data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
            timeout=10
        )
        
        result = response.json()
        
        if response.status_code == 200 and result.get("code") == 0:
            print(f"✅ 飞书通知发送成功")
            return True
        else:
            print(f"❌ 飞书接口返回错误: {result}")
            return False
            
    except Exception as e:
        print(f"❌ 发送飞书消息失败: {type(e).__name__}: {e}")
        return False

def save_log_file(fund1_data: Dict[str, Any], fund2_data: Dict[str, Any], 
                  premium_diff: float, is_alert: bool):
    """
    保存运行日志到文件
    无论是否触发通知，都生成日志文件
    """
    try:
        # 创建日志文件名
        log_filename = f"monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # 写入日志内容
        with open(log_filename, 'w', encoding='utf-8') as f:
            f.write(f"📅 监控时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*50 + "\n")
            f.write(f"📈 基金溢价监控日志\n")
            f.write("="*50 + "\n\n")
            
            f.write(f"基金1: {fund1_data['fund_code']} {fund1_data['fund_name']}\n")
            f.write(f"  实时价格: {fund1_data['price']:.4f} 元\n")
            f.write(f"  单位净值: {fund1_data['nav']:.4f} 元\n")
            f.write(f"  净值日期: {fund1_data['nav_date']}\n")
            f.write(f"  溢价率: {fund1_data['premium']:.3f}%\n\n")
            
            f.write(f"基金2: {fund2_data['fund_code']} {fund2_data['fund_name']}\n")
            f.write(f"  实时价格: {fund2_data['price']:.4f} 元\n")
            f.write(f"  单位净值: {fund2_data['nav']:.4f} 元\n")
            f.write(f"  净值日期: {fund2_data['nav_date']}\n")
            f.write(f"  溢价率: {fund2_data['premium']:.3f}%\n\n")
            
            f.write("="*50 + "\n")
            f.write(f"📊 计算结果\n")
            f.write("="*50 + "\n")
            f.write(f"溢价差: {premium_diff:.3f}%\n")
            f.write(f"触发阈值: <{THRESHOLD}%\n")
            f.write(f"触发状态: {'已触发' if is_alert else '未触发'}\n")
            f.write(f"飞书通知: {'已发送' if is_alert else '未发送'}\n")
            f.write(f"数据时间: {fund1_data['data_time']}\n")
        
        print(f"📄 日志文件已保存: {log_filename}")
        return log_filename
        
    except Exception as e:
        print(f"❌ 保存日志文件失败: {e}")
        return None

def main():
    """
    主监控函数
    """
    print("\n" + "="*80)
    print(f"💰 基金溢价监控系统（完整版）启动")
    print(f"⏰ 北京时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 监控频率: 每3分钟一次")
    print(f"📈 监控基金: 513100, 159632")
    print(f"⚡ 触发阈值: 溢价差 < {THRESHOLD}%")
    print(f"📊 核心特性: 使用同一交易日净值，确保公平比较")
    print("="*80)
    
    # 1. 获取同一交易日的单位净值
    fund1_nav_data, fund2_nav_data = get_latest_common_nav()
    
    if not fund1_nav_data or not fund2_nav_data:
        print("❌ 净值获取失败，本次监控终止")
        return
    
    # 2. 获取实时价格（使用股票行情接口）
    print("\n📡 正在获取ETF实时交易价格...")
    
    fund1_price_data = get_etf_realtime_price('513100')
    fund2_price_data = get_etf_realtime_price('159632')
    
    if not fund1_price_data or not fund2_price_data:
        print("❌ 价格获取失败，本次监控终止")
        return
    
    print("✅ 价格获取完成")
    
    # 3. 计算溢价率（使用同一交易日净值）
    fund1_premium = (fund1_price_data['price'] / fund1_nav_data['nav'] - 1) * 100
    fund2_premium = (fund2_price_data['price'] / fund2_nav_data['nav'] - 1) * 100
    
    # 4. 计算溢价差
    premium_diff = fund1_premium - fund2_premium
    
    # 5. 准备数据
    fund1_data = {
        'fund_code': '513100',
        'fund_name': fund1_price_data['fund_name'],
        'price': fund1_price_data['price'],
        'nav': fund1_nav_data['nav'],
        'nav_date': fund1_nav_data['date'],
        'premium': round(fund1_premium, 3),
        'update_time': fund1_price_data['update_time'],
        'data_time': fund1_price_data['data_time']
    }
    
    fund2_data = {
        'fund_code': '159632',
        'fund_name': fund2_price_data['fund_name'],
        'price': fund2_price_data['price'],
        'nav': fund2_nav_data['nav'],
        'nav_date': fund2_nav_data['date'],
        'premium': round(fund2_premium, 3),
        'update_time': fund2_price_data['update_time'],
        'data_time': fund2_price_data['data_time']
    }
    
    # 6. 显示计算结果
    print(f"\n📊 **计算结果（基于{fund1_data['nav_date']}净值）**")
    print(f"  {fund1_data['fund_code']} (SH):")
    print(f"    实时价格: {fund1_data['price']:.4f} 元")
    print(f"    单位净值: {fund1_data['nav']:.4f} 元")
    print(f"    溢价率: {fund1_data['premium']:.3f}%")
    
    print(f"\n  {fund2_data['fund_code']} (SZ):")
    print(f"    实时价格: {fund2_data['price']:.4f} 元")
    print(f"    单位净值: {fund2_data['nav']:.4f} 元")
    print(f"    溢价率: {fund2_data['premium']:.3f}%")
    
    print(f"\n  ➤ 溢价差: {premium_diff:.3f}%")
    print(f"  🎯 触发阈值: <{THRESHOLD}%")
    
    # 7. 保存日志文件（无论是否触发通知都保存）
    is_alert = premium_diff < THRESHOLD
    log_file = save_log_file(fund1_data, fund2_data, premium_diff, is_alert)
    
    # 8. 判断是否触发通知
    if is_alert:
        print(f"\n🚨 **触发告警**")
        print(f"   溢价差 {premium_diff:.3f}% < 阈值 {THRESHOLD}%")
        
        # 9. 发送飞书通知
        print("📱 正在发送飞书通知...")
        success = send_feishu_notification(fund1_data, fund2_data, premium_diff)
        
        if success:
            print("✅ 监控完成：告警已发送")
        else:
            print("⚠️  监控完成：但通知发送失败")
    else:
        print(f"\n✅ **未触发告警**")
        print(f"   溢价差 {premium_diff:.3f}% ≥ 阈值 {THRESHOLD}%")
        print("💡 监控正常，未达到触发条件")
    
    print(f"\n📁 本次监控详情已保存到日志文件: {log_file}")
    print("\n" + "="*80)
    print("⏳ 监控周期结束，3分钟后自动再次检查...")
    print("="*80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 监控被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 监控程序发生错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
