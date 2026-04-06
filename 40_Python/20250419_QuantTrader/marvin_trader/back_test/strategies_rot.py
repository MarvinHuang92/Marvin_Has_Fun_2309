import pandas as pd
from strategies import Strategy

"""
本文档定义所有的轮动策略

接口定义:
除了在"非轮动策略"中包括的列, 策略需额外在data中添加如下列:
"Choice" 列: 表示下一个交易日持有的股票序号, 从1开始计数, 0表示空仓

在 trader.py 中已经生成如下列，可以直接使用：
"Daily_Return_1", "Daily_Return_2"... 表示每只股票当天的收益
"Avg_Return_1", "Avg_Return_2"... 表示每只股票过去N天的平均收益 (含当天)
"Buy_Return_1", "Buy_Return_2"... 今天买入的收益 (今收-今开)
"Sell_Return_1", "Sell_Return_2"... 今天卖出的收益 (今开-昨收)

"""

# 基类
class StrategyRotation(Strategy):
    
    def getDailyReturnByIndex(self, col_index, data):
        col_index_striped = col_index.strip('Daily_Return_')
        if col_index_striped == '' or col_index_striped == '0':
            return '0'
        else:
            return data[col_index]
        
    def calcRivisedReturn(self, col_index_k1, col_index_k2, data):
        # 简单算法
        if not self.Rivise_Return:
            return self.getDailyReturnByIndex(col_index_k1, data)

        # 复杂算法，考虑开盘时才能交易
        else:  # elif self.Rivise_Return:
            col_index_striped_k1 = col_index_k1.strip('Daily_Return_')
            col_index_striped_k2 = col_index_k2.strip('Daily_Return_')
            # # 前两行数据不全时
            # if col_index_striped_k2 == '' or col_index_striped_k1 == '':
            #     return '0'
            # 连续两天空仓，收益=0
            if col_index_striped_k2 == '' and col_index_striped_k1 == '':
                return '0'
            # 昨日空仓，今早买入：收益=今收-今开
            elif col_index_striped_k2 == '':
                return data['Buy_Return_' + col_index_striped_k1] - self.trade_cost
            # 昨日持有，今早卖出：收益=今开-昨收
            elif col_index_striped_k1 == '':
                return data['Sell_Return_' + col_index_striped_k2] - self.trade_cost
            # 两天都持有同一只股票：收益=今收-昨收
            elif col_index_striped_k2 == col_index_striped_k1:
                return data[col_index_k1]
            # 更换股票：视作先卖掉昨日持有的，再买入今天的
            else:
                return (((1 + data['Sell_Return_' + col_index_striped_k2] - self.trade_cost) *
                        (1 + data['Buy_Return_' + col_index_striped_k1] - self.trade_cost)) - 1)

    # 第一轮调用：仅计算单只股票涨幅信息 Daily_Return and Avg_Return
    def calcSingleStockReturn(self, data):
        data = self.calcCommonInfo(data)
        return data
    
    # 第二轮调用：在子类中实现
    # def calcChoice(self):
    #     pass

    # 第三轮调用：计算今日收益
    def calcStrategyReturn(self, data):
        # 输出昨日选择目标股票的今日涨幅：【注意shift(1)下移一行，表示时间差】，空仓输出0
        data['Choice_K1'] = data['Choice'].shift(1)
        data['Choice_K2'] = data['Choice'].shift(2)
        data['Strategy_Return'] = data.apply(lambda data: self.calcRivisedReturn(
            "Daily_Return_" + str(data['Choice_K1']).strip('.0'), 
            "Daily_Return_" + str(data['Choice_K2']).strip('.0'), data), axis=1)
        
        # 转换格式str -> float
        data['Strategy_Return'] = pd.to_numeric(data['Strategy_Return'])

        # 计算轮动策略的累计收益
        # 但不计算原始个股的锁仓收益，因为轮动数据表中，只有第一只个股的收益率
        data = self.calcCumulativeReturn(data, calc_stock_CR=False)

        return data
    

# 子类 

# 多股轮动策略
class StrategyMultiTargetRotation(StrategyRotation):
    def __init__(self):
        super().__init__()
        self.name = "MultiTargetRotation"
        # 平均涨跌幅计算天数，越大越稳健
        self.avg_period = 20
        # 设置止损线：正值：稳健，负值：激进，设为-1表示没有止损
        self.X_up = -0.1  # 当日止损线
        self.R_up = 0.014  # 平均涨跌幅止损线

    # 第二轮调用：计算选择哪只股票
    def calcChoice(self, data, num=1):
        # 比较所有个股的平均涨幅，选取最大值所在列
        # AR = Avg_Return, DR = Daily_Return
        compare_range = []
        for i in range(num):
            compare_range.append('Avg_Return_%s' % str(i+1))
        data['Avg_Return_Max'] = data[compare_range].max(axis=1)
        data['ARMax_index'] = data[compare_range].idxmax(axis=1) #, skipna=True)
        data['ARMax_index'] = data.apply(lambda data: str(data['ARMax_index']).strip("nan").strip("Avg_Return_"), axis=1)
        
        # 计算平均涨幅最大的个股，对应的当天涨幅
        data['DR_on_ARMax_index'] = data.apply(lambda data: self.getDailyReturnByIndex(
            "Daily_Return_" + str(data['ARMax_index']), data), axis=1)
        
        # 转换格式str -> float
        data['ARMax_index'] = pd.to_numeric(data['ARMax_index'])
        data['DR_on_ARMax_index'] = pd.to_numeric(data['DR_on_ARMax_index'])
        
        # 生成选股信号：若平均涨幅最大的个股，对应的当天涨幅超过止损线，输出其序号到Choice，否则输出0（默认值）
        data.loc[(data['DR_on_ARMax_index'] >= self.X_up) & (data['Avg_Return_Max'] >= self.R_up), 'Choice'] = data['ARMax_index']

        return data