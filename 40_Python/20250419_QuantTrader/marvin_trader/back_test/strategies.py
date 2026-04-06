# import pandas as pd

"""
本文档定义所有的非轮动策略

接口定义:
策略需在data中添加如下列:
"Signal" 列: 表示下一个交易日的仓位, 0为空仓, 1为满仓
"Strategy_Return" 列: 每个交易日的收益率, 注意: 与上一个交易日的仓位相关
"Cumulative_Return" 列: 策略累计收益率
"Stock_Cumul_Return" 列: 锁仓累计收益率

以下两行暂时不需要, 节约算力:
"Abnormal_Return_Rel" 列: 当天相对超额收益率 (策略收益 Strategy_Return / 锁仓收益 Daily_Return)-1
"Abnormal_Return_Abs" 列: 当天绝对超额收益率 (策略收益 Strategy_Return - 锁仓收益 Daily_Return)

"Cumulative_Abnormal_Return": 累计相对超额收益 (CAR), 表格中不计算, 只在打印log时计算:
最后一天的 Cumulative_Return / Stock_Cumul_Return - 1

"""


# 基类
class Strategy():
    def __init__(self):
        self.name = "strategy_base_class"
        self.Rivise_Return = True
        self.trade_cost = 0
        self.AvgDays_Near = 9
        self.AvgDays_Far = 99
        self.avg_period = 99
    
    def calcCommonInfo(self, data):
        # 计算相较昨日的涨跌幅（昨收->今收）
        data['Daily_Return'] = data['Close'].pct_change(fill_method=None)  # for yfinance
        # data['Daily_Return'] = data['pctChg'] / 100.0  # for baostock (百分比，需要除以100)
        # 考虑操作窗口的涨跌幅
        # 今开->今收
        data['Buy_Return'] = (data['Close'] - data['Open']) / data['Open']
        # 昨收->今开
        data['Sell_Return'] = (data['Open'] - data['Close'].shift(1)) / data['Close'].shift(1)
        # 计算过去N个交易日平均涨跌幅
        # data['Sum_Return'] = (data['Close'] - data['Close'].shift(self.avg_period)) / data['Close'].shift(self.avg_period)
        # data['Avg_Return'] = data['Sum_Return'] / self.avg_period
        data['Avg_Return'] = data['Close'].pct_change(self.avg_period, fill_method=None)
        # 计算短期和长期移动平均
        data['MA_Near'] = data['Close'].rolling(window=self.AvgDays_Near).mean()
        data['MA_Far'] = data['Close'].rolling(window=self.AvgDays_Far).mean()
        # 初始化Signal值(表示买卖动作，也表示仓位：0卖出至空仓，1买入至满仓)
        data['Signal'] = 0
        return data
    
    def calcCumulativeReturn(self, data, calc_stock_CR=True):
        # 计算累计收益
        # cumprod() 累计做乘法，可以体现复利
        data['Cumulative_Return'] = (1 + data['Strategy_Return']).cumprod()
        # 仅在非轮动策略时计算
        if calc_stock_CR:
            data['Stock_Cumul_Return'] = (1 + data['Daily_Return']).cumprod()
            # data['Abnormal_Return_Rel'] = data['Strategy_Return'] / data['Daily_Return'] - 1
            # data['Abnormal_Return_Abs'] = data['Strategy_Return'] - data['Daily_Return']
        return data

    def calcRivisedReturn(self, data):
        # 假设交易时间窗口为集合竞价时，如果当晚决定交易，次日收益率需要修正
        # OptCode = 前天Signal+昨天Signal*2
        # 00 -> 0, 01 -> 2, 10 -> 1, 11 -> 3
        
        # 昨日空仓，今早买入：收益=今收-今开
        if data['OptCode'] == 2:
            return data['Buy_Return'] - self.trade_cost
        # 昨日持有，今早卖出：收益=今开-昨收
        elif data['OptCode'] == 1:
            return data['Sell_Return'] - self.trade_cost
        # 两天都持有：收益=今收-昨收
        elif data['OptCode'] == 3:
            return data['Daily_Return']
        # 两天都空仓，或数据不全时，收益=0
        else: # data['OptCode'] == 0:
            return 0

    def calcStrategyReturn(self, data):
        # 简单算法，不考虑操作窗口，收益=今收-昨收
        if not self.Rivise_Return:
            # 计算今日收益率 = 今天涨幅*仓位（data['Signal']表示仓位）
            # 若今天跌了，收益率为负
            # 若今天空仓，收益率=0
            # shift(1)将data向下平移一行，第一行留空NaN
            data['Strategy_Return'] = data['Signal'].shift(1) * data['Daily_Return']

        # 考虑操作窗口，计算当天收益率
        else: # elif self.Rivise_Return:
            data['OptCode'] = data['Signal'].shift(1) * 2 + data['Signal'].shift(2)
            data['Strategy_Return'] = data.apply(lambda data: self.calcRivisedReturn(data), axis=1)
        
        # 计算累计收益
        data = self.calcCumulativeReturn(data)
        return data


# 子类

# 移动均线策略
class StrategyMoveAvg(Strategy):
    def __init__(self):
        super().__init__()
        self.name = "stategy_move_avg"
        self.AvgDays_Near = 10
        self.AvgDays_Far = 60
    
    # 计算仓位
    def calcPosition(self, data):
        data = self.calcCommonInfo(data)
        # 生成买卖信号
        data.loc[data['MA_Near'] > data['MA_Far'], 'Signal'] = 1  # 短期均线上穿长期均线，产生买入信号，满仓
        # data.loc[data['MA_Near'] < data['MA_Far'], 'Signal'] = 0  # 短期均线下穿长期均线，产生卖出信号，空仓（默认为0）

        # 限制条件
        # 长期均线未生成时，策略不生效，认为始终满仓，策略收益率=实际收益率
        data.loc[data['RowIndex'] < self.AvgDays_Far, 'Signal'] = 1

        return data


# 昨日收益率二值化策略
class StrategyYesterdayReturnBinarized(Strategy):
    def __init__(self):
        super().__init__()
        self.name = "stategy_yestRetBin"
        self.X_up = 0.015  # 当日止损线 （正值：稳健，负值：激进，设为-1表示没有止损）
    
    # 计算仓位
    def calcPosition(self, data):
        data = self.calcCommonInfo(data)
        # 生成买卖信号
        # 昨天涨了，则今天开盘时全仓买入
        # 昨天跌了，今天空仓
        data.loc[data['Daily_Return'] >= self.X_up, 'Signal'] = 1  # 以昨日涨幅为信号，涨幅超过止损线则满仓，否则空仓
        return data


# 移动窗口高抛低吸策略
class StrategyRollingMinMax(Strategy):
    def __init__(self):
        super().__init__()
        self.name = "RollingMinMax"
        self.rolling_window = 300  # 统计过去N天的价格区间
        self.Buy_ratio = 0.03  # 在最低价以上多少比例买入
        self.Sell_ratio = 0.02  # 在最高价以下多少比例卖出

    # 计算仓位
    def calcPosition(self, data):
        data = self.calcCommonInfo(data)
        
        # 添加移动最大值和最小值列
        data['History_Max'] = data['Close'].rolling(window=self.rolling_window).max()
        data['History_Min'] = data['Close'].rolling(window=self.rolling_window).min()

        # 生成买卖信号
        # data.loc[(data['Close'] <= data['History_Min'] * (1 + self.Buy_ratio)), 'Signal'] = 1
        # data.loc[(data['Close'] >= data['History_Max'] * (1 - self.Sell_ratio)), 'Signal'] = 0

        # 限制条件
        # 历史价格窗口未生成时，策略不生效，认为始终满仓，策略收益率=实际收益率
        data.loc[data['RowIndex'] < self.rolling_window - 1, 'Signal'] = 1
        
        # 遍历所有行
        for i in range(self.rolling_window - 1, len(data)):
            r_close = data.at[i, 'Close']
            r_min = data.at[i, 'History_Min']
            r_max = data.at[i, 'History_Max']
            # 买入条件
            if r_close <= r_min * (1 + self.Buy_ratio):
                data.at[i, 'Signal'] = 1
            # 卖出条件
            elif r_close >= r_max * (1 - self.Sell_ratio):
                data.at[i, 'Signal'] = 0
            # 不满足买卖两个条件的，将继承上一行的Signal值
            else:
                data.at[i, 'Signal'] = data.at[i - 1, 'Signal']
        
        return data


# 自定义策略
class StrategyCustomize(Strategy):
    def __init__(self):
        super().__init__()
        self.name = "Customize"  # dummy，下面会改写
        self.avg_period = 9  # 平均涨跌幅计算天数
        self.R_up = 0.015  # 平均涨幅阈值
        self.X_up = -0.03  # 当日止损线 （正值：稳健，负值：激进，设为-1表示没有止损）
        self.R_down = -0.005  # 平均跌幅阈值

    # 计算仓位
    def calcPosition(self, data):
        data = self.calcCommonInfo(data)
        
        # 生成买卖信号

        # # 超跌反弹策略:
        # self.name = "OversoldRebound"
        # # 平均跌幅超过0.5%，且昨天为正收益，则买入，否则空仓
        # data.loc[(data['Avg_Return'] < self.R_down) & (data['Daily_Return'] >= self.X_up), 'Signal'] = 1

        # 连续上涨策略 * 移动均线：
        self.name = "ContinuousUptrend"
        # 平均涨幅超过R_up，且昨天为正收益，则买入，否则空仓
        data.loc[(data['Avg_Return'] > self.R_up) & (data['Daily_Return'] >= self.X_up) & (data['MA_Near'] > data['MA_Far']), 'Signal'] = 1

        # # 连续上涨-超跌反弹组合策略：
        # self.name = "ContinuousUptrendOrOversoldRebound"
        # data.loc[((data['Avg_Return'] > self.R_up) | (data['Avg_Return'] < self.R_down)) & (data['Daily_Return'] >= self.X_up), 'Signal'] = 1

        # 限制条件
        # 长期均线未生成时，策略不生效，认为始终满仓，策略收益率=实际收益率
        data.loc[data['RowIndex'] < self.AvgDays_Far, 'Signal'] = 1

        return data
    