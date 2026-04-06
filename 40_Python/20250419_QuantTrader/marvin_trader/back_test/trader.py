import os
import pandas as pd
import time
# import yfinance as yf
import baostock as bs
import matplotlib.pyplot as plt
from strategies import *
from strategies_rot import *
from csv_data_proc import *

########################## 参数设置 ##########################

# 单次交易成本
trade_cost = 0.0004

# 全年交易日
annual_T_days = 243

# 是否更新数据库
# update_database = True
update_database = False

# 更新数据库的时间范围
update_database_from = "2010-1-1"
update_database_to = "2025-5-30"

# 是否显示股价图
# show_plot = True
show_plot = False

# 是否执行轮动策略
rotation = True
# rotation = False

# 是否每次重新下载股票数据
# 更改K线频率后，需要重新下载数据
# re_download_data = True
re_download_data = False

############### 如果采用轮动策略，将使用如下设置 ###############
############### 否则，将使用 input/Stock_list.csv 的设置 ######

# 轮动个股
rotation_symbol_list = [
    "sh.000300",  # 沪深300
    # "sh.000852",  # 中证1000
    # "sz.399006",  # 创业板指
    # "sz.399249",  # 综企指数
    # "sz.399296",  # 创成长
    # "sz.399303",  # 国证2000
    "sz.399673",  # 创业板50
    # "sz.399905",  # 中证500
    # "sz.399967",  # 中证军工
    # "sh.600489",  # 中金黄金
    # "sh.600828",  # 茂业商业
    # "sh.601988",  # 中国银行
    # "sz.H30269",  # 红利低波指数，无数据
    # "sh.600900",  # 长江电力
    # "sh.600919",  # 江苏银行

    # "sh.000049",

    # 综企指数成分股
    # "sz.000532",  # 华金资本
    # "sz.000833",  # 粤桂股份

    # "sz.511260",  # 军工ETF，无数据

    # symbol	start_date	end_date	Final_Return
    # "sz.399249", #	2014/1/1	2025/4/30	20.8521
    # "sz.399967", #	2014/1/1	2025/4/30	11.7403
    # "sz.399236", #	2014/1/1	2025/4/30	9.6561
    # "sz.399368", #	2014/1/1	2025/4/30	8.524
    # "sz.399360", #	2014/1/1	2025/4/30	7.6734
    # "sz.399959", #	2014/1/1	2025/4/30	7.6217
    # "sz.399409", #	2014/1/1	2025/4/30	6.9314
    # "sh.000852", #	2014/1/1	2025/4/30	6.6378
    # "sz.399666", #	2014/1/1	2025/4/30	6.4925
    # "sz.399010", #	2014/1/1	2025/4/30	6.3802
    # "sz.399664", #	2014/1/1	2025/4/30	6.3363
    # "sz.399239", #	2014/1/1	2025/4/30	6.1979
    # "sz.399303", #	2014/1/1	2025/4/30	6.1002
    # "sz.399628", #	2014/1/1	2025/4/30	6.0149

]

# 轮动起止时间
rotation_dates = [
    # 全周期
    # ["2014-1-1", "2025-4-30"],
    # ["2019-1-1", "2025-4-30"],

    # 短周期
    # ["2025-1-1", "2025-5-9"],
    
    # 一年窗口期
    # ["2014-1-1", "2014-12-31"],
    ["2015-1-1", "2015-12-31"],
    ["2016-1-1", "2016-12-31"],
    ["2017-1-1", "2017-12-31"],
    ["2018-1-1", "2018-12-31"],
    ["2019-1-1", "2019-12-31"],
    ["2020-1-1", "2020-12-31"],
    ["2021-1-1", "2021-12-31"],
    ["2022-1-1", "2022-12-31"],
    ["2023-1-1", "2023-12-31"],
    ["2024-1-1", "2024-12-31"],

    # 三年窗口期
    # ["2014-1-1", "2016-12-31"],
    # ["2015-1-1", "2017-12-31"],
    # ["2016-1-1", "2018-12-31"],
    # ["2017-1-1", "2019-12-31"],
    # ["2018-1-1", "2020-12-31"],
    # ["2019-1-1", "2021-12-31"],
    # ["2020-1-1", "2022-12-31"],
    # ["2021-1-1", "2023-12-31"],
    # ["2022-1-1", "2024-12-31"],
]

##############################################################

Is_baostock_login = False

def baostock_get_data(symbol, start_date, end_date, csv_path=None):

    #### 登陆系统 ####
    global Is_baostock_login
    if not Is_baostock_login:
        lg = bs.login()
        # 显示登陆返回信息
        print('login respond error_code:'+lg.error_code)
        print('login respond error_msg:'+lg.error_msg)
        Is_baostock_login = True

    #### 获取历史K线数据 ####
    # 详细指标参数，参见“历史行情指标参数”章节
    # http://baostock.com/baostock/index.php/A股K线数据
    # 如添加更多指标参数，需注意数据类型转换(默认都是str)
    # attributes = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    # 移除不常用的指标
    attributes = "date,code,open,high,low,close,volume,amount,turn,pctChg"
    # frequency="d"取日k线，adjustflag="3"默认不复权
    rs = bs.query_history_k_data_plus(symbol, attributes, start_date, end_date, frequency="d", adjustflag="3")
    print('query_history_k_data_plus respond error_code:'+rs.error_code)
    print('query_history_k_data_plus respond error_msg:'+rs.error_msg)

    #### 获取结果集 ####
    data_list = []
    while (rs.error_code == '0') & rs.next():
        # 获取一条记录，将记录合并在一起
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)

    #### 登出系统 ####
    # bs.logout()  # 脚本整体结束时再登出

    # 数据类型转换：将str转为数值（暂只对常用指标转换，如需要可添加更多）
    result["Open"] = pd.to_numeric(result["open"])  # 为了适配yfinance脚本风格，首字母大写
    result["High"] = pd.to_numeric(result["high"])  # 为了适配yfinance脚本风格，首字母大写
    result["Low"] = pd.to_numeric(result["low"])    # 为了适配yfinance脚本风格，首字母大写
    result["Close"] = pd.to_numeric(result["close"])# 为了适配yfinance脚本风格，首字母大写
    # result["preclose"] = pd.to_numeric(result["preclose"])
    result["volume"] = pd.to_numeric(result["volume"])
    result["amount"] = pd.to_numeric(result["amount"])
    result["turn"] = pd.to_numeric(result["turn"])

    # 给每一行添加索引，方便后面调用
    result = result.reset_index(drop=True)  # 重置原始索引，否则切片的数据作比较时，原始索引不同，会出问题
    result['RowIndex'] = range(len(result.iloc[:]))  # 添加新索引列

    if csv_path:
        write_to_csv(result, csv_path)

    return result

def create_output_dir():
    if not os.path.isdir("output"):
        os.mkdir("output")
    if not os.path.isdir("output/svg_plot"):
        os.mkdir("output/svg_plot")
    if not os.path.isdir("output/csv_rawdata"):
        os.mkdir("output/csv_rawdata")
    if not os.path.isdir("output/csv_strategy"):
        os.mkdir("output/csv_strategy")
    if not os.path.isdir("log"):
        os.mkdir("log")
    if not os.path.isdir("log/statistics"):
        os.mkdir("log/statistics")

# 允许将 DataFrame 写到多个csv文件
def write_to_csv(df, output_path):
    if not isinstance(output_path, list):
        output_path = [output_path,]
    for o_path in output_path:
        df.to_csv(o_path, encoding="gbk", index=False)

def get_stock_list(input_csv):
    # 忽略csv注释中的中文编码错误
    data = pd.read_csv(input_csv, encoding="utf_8", encoding_errors="ignore")

    data = data.iloc[1:]  # 丢弃第一行（中文注释）
    data = data.drop(["comment", "Unnamed: 6"], axis=1)  # 丢弃指定的列

    # 修改日期格式
    data['start_date'] = data.apply(lambda data: data['start_date'].replace("/", "-"), axis=1)
    data['end_date'] = data.apply(lambda data: data['end_date'].replace("/", "-"), axis=1)
    # 将yfinance的股票代码格式适配为baostock的格式
    def symbol_adaptation(symbol_str):
        if ".SS" in symbol_str:
            symbol_str = "sh." + symbol_str.strip(".SS")
        elif ".SZ" in symbol_str:
            symbol_str = "sz." + symbol_str.strip(".SZ")
        return symbol_str
    data['symbol'] = data.apply(lambda data: symbol_adaptation(data['symbol']), axis=1)

    # records是内置参数，将dataframe转换为字典列表 [{}, {}, ...] 的格式
    dict_from_df = data.to_dict("records")
    # print(dict_from_df)

    return dict_from_df

# 根据复利，计算年化收益
def calcAnnualRet(final_ret, t_days):
    # avg_daily_ret = final_ret**(1 / t_days) - 1
    # annual_ret = (1 + avg_daily_ret)**annual_T_days
    return final_ret**(annual_T_days / t_days)

def main(stock_info, strategy, rotation=False):
    global quick_test_symbol
    global quick_test_symbol_2
    global quick_test_start_date
    global quick_test_end_date
    global quick_test_T_Days
    global quick_test_C_Return
    global quick_test_S_Return
    global quick_test_CAR
    global quick_test_A_Return

    # # 获取股票数据，后缀上海=SS，深圳=SZ
    # # 多只股票可定义为列表
    # # symbol = "000300.SS"  # 沪深300指数
    # symbol = "159919.SZ"  # 沪深300ETF
    # start_date = "2018-01-01"
    # end_date = "2025-04-18"

    if rotation:  # 轮动策略，stock_info输入应当为列表
        if not type(stock_info).__name__ == "list":
            print("ERROR: 'stock_info' shall be list for rotation strategy!\n")
            exit(-1)

    else:  # 非轮动策略，stock_info如果是列表，只取第一个元素，如果不是，组装成列表
        if type(stock_info).__name__ == "list":
            stock_info = stock_info[:1]
        else:
            stock_info = [stock_info,]

    # 日期按第一只股票信息为准
    start_date = stock_info[0]["start_date"]
    end_date = stock_info[0]["end_date"]

    # 遍历所有股票信息，若不是轮动策略，list只有一个元素
    data_list = []
    symbol_list = []
    for stock in stock_info:
        symbol = stock["symbol"]
        symbol_list.append(symbol)

        # 以下部分仅针对一只股票操作：
        # 更新数据库
        if update_database:
            print("Updating database: %s from %s to %s..." % (symbol, update_database_from, update_database_to))
            # 清理旧的csv文件
            os.system("del /q %s\\*%s*.csv" % (newdata_dir, symbol))
            # 下载新的csv文件
            new_database_name = "history_k_data_%s_%s_%s.csv" % (symbol, update_database_from, update_database_to)
            new_database_path = os.path.join(newdata_dir, new_database_name)
            baostock_get_data(symbol, update_database_from, update_database_to, new_database_path)
            # 将新数据与原数据合并
            merge_rawdata(symbol, keep_origin_data=False)

        # 获取股票的历史交易信息
        # data = yf.download(symbol, start=start_date, end=end_date, auto_adjust=False)
        csv_path = "output/csv_rawdata/history_k_data_%s_%s_%s.csv" % (symbol, start_date, end_date)
        # 尝试读取已有的（日期范围一致的）csv
        if (not re_download_data) and (os.path.exists(csv_path)):
            data = pd.read_csv(csv_path)
        else:  
            # 若不存在，尝试从已有总数据库中，提取特定日期范围的数据切片，并将结果集输出到csv
            try:
                data = split_rawdata(symbol, start_date, end_date)
            # 若提取失败，尝试从baostock搜索，并将结果集输出到csv
            except:
                data = baostock_get_data(symbol, start_date, end_date, csv_path)
        # 如果未成功下载数据，会得到空的dataFrame，跳过
        if data.empty:
            print("WARNING: '%s' data download failed!\n" % symbol)
            break
        else:
            print("'%s' data loaded successully." % symbol)
            print(data.head())  # 不加参数，默认显示5行
            print("")  # 空白行

        if rotation:
            data_list.append(data)
        # 非轮动策略：
        else:
            ########## 执行交易策略 ##########
            # 计算每日交易仓位
            data = strategy.calcPosition(data)

            ########## 回测 ##########
            # 计算策略收益和累计收益
            data = strategy.calcStrategyReturn(data)
            t_days = len(data)
            strategy_ret = data.iloc[-1]['Cumulative_Return']
            stock_ret = data.iloc[-1]['Stock_Cumul_Return']
            cumul_ab_ret = strategy_ret / stock_ret - 1
            annual_ret = calcAnnualRet(strategy_ret, t_days)
            print("Stock '%s' from %s to %s" % (symbol, start_date, end_date))
            print("Trade Days     : %d" % t_days)
            print("Strategy Return: %.4f" % strategy_ret)
            print("Stock Return   : %.4f" % stock_ret)
            print("Abnormal Return: %.4f" % cumul_ab_ret)
            print("Annual Return  : %.4f" % annual_ret)
            print("")

            quick_test_symbol.append(symbol)
            quick_test_start_date.append(start_date)
            quick_test_end_date.append(end_date)
            quick_test_T_Days.append("%d" % t_days)
            quick_test_C_Return.append("%.4f" % strategy_ret)
            quick_test_S_Return.append("%.4f" % stock_ret)
            quick_test_CAR.append("%.4f" % cumul_ab_ret)
            quick_test_A_Return.append("%.4f" % annual_ret)

            # 输出包含该策略参数的csv
            csv_strategy_filename = "Strategy_Data_%s_%s_%s_%s_Avg_%d_%d" % (strategy.name, symbol, start_date, end_date, 
                                                                            strategy.AvgDays_Near, strategy.AvgDays_Far)
            write_to_csv(data, "output/csv_strategy/%s.csv" % csv_strategy_filename)

            ########## 绘图 ##########
            plt.figure(figsize=(10, 8))
            # # 拆分为2行1列，fig表示总图，ax1, ax2表示两个子图，共享x轴
            # fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True)

            # plot 1:绘制股价和移动平均线
            plt.subplot(2, 1, 1)
            plt.plot(data['Close'], label='Close Price')
            if strategy.name == "RollingMinMax":
                plt.plot(data['History_Min'], label='%d-day Min Price' % strategy.rolling_window)
                plt.plot(data['History_Max'], label='%d-day Max Price' % strategy.rolling_window)
            else:
                plt.plot(data['MA_Near'], label='%d-day Moving Average' % strategy.AvgDays_Near)
                plt.plot(data['MA_Far'], label='%d-day Moving Average' % strategy.AvgDays_Far)

            # 标记买卖信号
            if strategy.name == "RollingMinMax":
                plt.scatter(data[data['Signal'] == 1].index, data[data['Signal'] == 1]['Close'], marker='^', color='g', label='Buy Signal')
                plt.scatter(data[data['Signal'] == 0].index, data[data['Signal'] == 0]['Close'], marker='v', color='r', label='Sell Signal')
            else:
                plt.scatter(data[data['Signal'] == 1].index, data[data['Signal'] == 1]['MA_Near'], marker='^', color='g', label='Buy Signal')
                plt.scatter(data[data['Signal'] == 0].index, data[data['Signal'] == 0]['MA_Near'], marker='v', color='r', label='Sell Signal')

            plt.title("Stock Price with Moving Averages")
            # 不显示第一张图的x轴刻度和label
            # plt.xlabel("Date")
            ax = plt.gca()
            ax.axes.xaxis.set_visible(False)
            plt.ylabel("Price (CNY)")
            plt.legend()

            # plot 2:绘制累计收益曲线
            plt.subplot(2, 1, 2)
            plt.plot(data['date'], data['Cumulative_Return'], label='Strategy Cumulative Return', color='b')
            # plt.plot(data['date'], data['Close'] / data['Close'].iloc[0], label='Stock Cumulative Return', color='g')
            plt.plot(data['date'], data['Stock_Cumul_Return'], label='Stock Cumulative Return', color='g')
            plt.title("Cumulative Return of Strategy vs. Stock")
            plt.xlabel("Date")
            plt.ylabel("Cumulative Return")
            plt.legend()

            # 设置x轴刻度间隔
            x_major_locator = plt.MultipleLocator(60)
            ax = plt.gca()
            ax.xaxis.set_major_locator(x_major_locator)
            # 旋转日期标签
            ax.xaxis.set_tick_params(rotation=45)

            plt.suptitle("%s Stock Return from %s to %s" % (symbol, start_date, end_date)) # 总图标题
            # plt.supxlabel("Date") # 总图共享x轴标签

            fig_fname = "Stock_Return_%s_%s_%s_%s_Avg_%d_%d" % (strategy.name, symbol, start_date, end_date, 
                                                                strategy.AvgDays_Near, strategy.AvgDays_Far)
            plt.savefig("output/svg_plot/%s.svg" % fig_fname, dpi=None, format="svg")  # 文件名包含格式，可省略 format="svg" 参数
            if show_plot:
                plt.show()  # 要在保存图片之后再 show() ，否则show()会重新生成一个新的图片，保存的是空图片
        
    # 轮动策略：
    if rotation:
        ########## 执行交易策略 ##########
        # 以第一只股票为基准，生成总表
        data_assembled = data_list[0]
        stoke_index = 0
        for data in data_list:
            stoke_index += 1

            # 检查数据长度是否一致
            if not(data["date"].equals(data_assembled["date"]) and
               data["RowIndex"].equals(data_assembled["RowIndex"])):
                print("ERROR: data 'date' or 'RowIndex' mismatch for rotation strategy!\n")
                exit(-1)
            
            # 第一轮计算：单只股票的涨幅信息
            data = strategy.calcSingleStockReturn(data)

            # 向总表中添加个股数据
            data_assembled["Daily_Return_%d" % stoke_index] = data["Daily_Return"]
            data_assembled["Avg_Return_%d" % stoke_index] = data["Avg_Return"]
            data_assembled["Buy_Return_%d" % stoke_index] = data["Buy_Return"]
            data_assembled["Sell_Return_%d" % stoke_index] = data["Sell_Return"]
    
        # 第二轮计算：基于总表，计算选股信号Choice
        data_assembled["Choice"] = 0  # 选中第几只股票，0表示空仓（默认）
        data_assembled = strategy.calcChoice(data_assembled, num=stoke_index)

        ########## 回测 ##########
        # 第三轮计算：今日收和累计收益
        data_assembled = strategy.calcStrategyReturn(data_assembled)
        t_days = len(data_assembled)
        strategy_ret = data_assembled.iloc[-1]['Cumulative_Return']
        annual_ret = calcAnnualRet(strategy_ret, t_days)
        print("Stock '%s' from %s to %s" % (str(symbol_list), start_date, end_date))
        print("Trade Days   : %d" % t_days)
        print("Final Return : %.4f" % strategy_ret)
        print("Annual Return: %.4f" % annual_ret)
        print("")

        quick_test_symbol.append(symbol_list[0])
        quick_test_symbol_2.append(symbol_list[1])
        quick_test_start_date.append(start_date)
        quick_test_end_date.append(end_date)
        quick_test_T_Days.append("%d" % t_days)
        quick_test_C_Return.append("%.4f" % strategy_ret)
        quick_test_A_Return.append("%.4f" % annual_ret)

        # 输出包含该策略参数的csv
        csv_rotation_filename = "RotationStrategy_Data_%s_%s_%s" % (str(symbol_list), start_date, end_date)
        write_to_csv(data_assembled, "output/csv_strategy/%s.csv" % csv_rotation_filename)

        ########## 绘图 ##########
        plt.figure(figsize=(10, 8))
        # # 拆分为2行1列，fig表示总图，ax1, ax2表示两个子图，共享x轴
        # fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True)
        color_list = ['c', 'b', 'g', 'm', 'y', 'k', 'w']

        # plot 1:绘制两只轮动股的股价图
        plt.subplot(2, 1, 1)
        for i in range(stoke_index):
            plt.plot(data_list[i]['Close'], label='Close Price %s' % str(i+1), color=color_list[i % len(color_list)])

            # 标记选股信号
            plt.scatter(data_assembled[data_assembled['Choice'] == i+1].index, 
                        data_list[i][data_assembled['Choice'] == i+1]['Close'], 
                        marker='^', color='r', label='Buy Signal %s' % str(i+1))

        plt.title("Stock Price %s" % str(symbol_list))
        # 不显示第一张图的x轴刻度和label
        # plt.xlabel("Date")
        ax = plt.gca()
        ax.axes.xaxis.set_visible(False)
        plt.ylabel("Price (CNY)")
        plt.legend()

        # plot 2:绘制累计收益曲线
        plt.subplot(2, 1, 2)
        plt.plot(data_assembled['date'], data_assembled['Cumulative_Return'], label='Strategy Cumulative Return', color='r')
        for i in range(stoke_index):
            plt.plot(data_assembled['date'], data_list[i]['Close'] / data_list[i]['Close'].iloc[0], 
                     label='Stock Cumulative Return %s' % str(i+1), color=color_list[i % len(color_list)])
        plt.title("Cumulative Return of Strategy vs. Stock")
        plt.xlabel("Date")
        plt.ylabel("Cumulative Return")
        plt.legend()

        # 设置x轴刻度间隔
        x_major_locator = plt.MultipleLocator(90)
        ax = plt.gca()
        ax.xaxis.set_major_locator(x_major_locator)
        # 旋转日期标签
        ax.xaxis.set_tick_params(rotation=45)

        plt.suptitle("%s Stock Rotation Return from %s to %s" % (str(symbol_list), start_date, end_date)) # 总图标题
        # plt.supxlabel("Date") # 总图共享x轴标签

        fig_fname = "Stock_Rotation_Return_%s_%s_%s" % (str(symbol_list), start_date, end_date)
        plt.savefig("output/svg_plot/%s.svg" % fig_fname, dpi=None, format="svg")  # 文件名包含格式，可省略 format="svg" 参数
        if show_plot:
            plt.show()  # 要在保存图片之后再 show() ，否则show()会重新生成一个新的图片，保存的是空图片


if __name__ == "__main__":
    create_output_dir()
    timestamp = time.strftime('%Y%m%d_%H%M%S', time.localtime(time.time()))

    # 快速测试：数据初始化
    quick_test_symbol = []
    quick_test_symbol_2 = []  # 仅用于轮动测试，暂时支持2只个股，超过2只的不打印名字
    quick_test_start_date = []
    quick_test_end_date = []
    quick_test_T_Days = []    # 交易日天数
    quick_test_C_Return = []  # 策略累计收益
    quick_test_S_Return = []  # 锁仓累计收益，轮动策略不包含
    quick_test_CAR = []       # 累计超额收益 Cumulative_Abnormal_Return，轮动策略不包含
    quick_test_A_Return = []  # 年化收益

    # 针对输入列表的每只股票，计算策略收益
    if not rotation:
        ########## 选择交易策略 ##########
        # 移动平均线策略
        # strategy = StrategyMoveAvg()
        # 昨日收益率二值化策略
        # strategy = StrategyYesterdayReturnBinarized()
        # 移动窗口高抛低吸策略
        strategy = StrategyRollingMinMax()
        # 连续上涨周期，或超跌反弹策略
        # strategy = StrategyCustomize()

        strategy.trade_cost = trade_cost
        for stock_info in get_stock_list("input/Stock_list.csv"):
            if not (stock_info['baostock_available'] == 'N'):
                main(stock_info, strategy)
        
        # 快速测试1：筛选高收益率个股
        df_quick_test = pd.DataFrame({
            "symbol": quick_test_symbol,
            "start_date": quick_test_start_date,
            "end_date": quick_test_end_date,
            "T_Days": quick_test_T_Days,
            "Strategy_Return": quick_test_C_Return,
            "Stock_Return": quick_test_S_Return,
            "CAR": quick_test_CAR,
            "Annual_Return": quick_test_A_Return,
        })
        write_to_csv(df_quick_test, ["log/statistics/%s_result_%s.csv" % (strategy.name, timestamp),
                                     "log/quick_test_result_1.csv"])
        
    # 轮动策略
    else:
        strategy = StrategyMultiTargetRotation()
        strategy.trade_cost = trade_cost
        for date in rotation_dates:
            stock_info_for_rotation = []
            for rotation_symbol in rotation_symbol_list:
                stock_info = {}
                stock_info["symbol"] = rotation_symbol
                stock_info["start_date"] = date[0]
                stock_info["end_date"] = date[1]
                stock_info_for_rotation.append(stock_info)
            main(stock_info_for_rotation, strategy, rotation=True)

        # 快速测试2：测试不同时间窗口收益率
        df_quick_test = pd.DataFrame({
            "symbol_1": quick_test_symbol,
            "symbol_2": quick_test_symbol_2,
            "start_date": quick_test_start_date,
            "end_date": quick_test_end_date,
            "T_Days": quick_test_T_Days,
            "Final_Return": quick_test_C_Return,
            "Annual_Return": quick_test_A_Return,
        })
        write_to_csv(df_quick_test, ["log/statistics/%s_result_%s.csv" % (strategy.name, timestamp),
                                     "log/quick_test_result_2.csv"])
    
    # 记录 strategy 成员属性
    # 生成包含所有成员属性的字典
    strategy_attr_dict = strategy.__dict__
    # 将字典转成 DataFrame
    strategy_attr_df = pd.DataFrame.from_dict(strategy_attr_dict, orient="index", columns=["values"])
    strategy_attr_df = strategy_attr_df.reset_index().rename(columns = {"index": "keys"})
    # 打印到console
    print("Strategy attributes:")
    print(strategy_attr_df)
    # 写入csv
    if not rotation:
        quick_test_attr_log_name = "log/quick_test_attributes_1.csv"
    else:
        quick_test_attr_log_name = "log/quick_test_attributes_2.csv"
    write_to_csv(strategy_attr_df, ["log/statistics/%s_attributes_%s.csv" % (strategy.name, timestamp),
                                     quick_test_attr_log_name])
    
    # 登出 baostock
    if Is_baostock_login:
        bs.logout()
        Is_baostock_login = False
    