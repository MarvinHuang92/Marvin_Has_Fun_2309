import pandas as pd

# 给股票代码添加交易所后缀
def get_exchange_loc(code_str):
    if code_str[0] == "0" or code_str[0] == "3":
        ret_1 = "sz." + code_str
        ret_2 = code_str + ".SZ"
    elif code_str[0] == "6":
        ret_1 = "sh." + code_str
        ret_2 = code_str + ".SS"
    else:
        ret_1 = "bj." + code_str
        ret_2 = code_str + ".BJ"
    return ret_1, ret_2

contents = []
with open("all_stock_list.csv", encoding="utf-8") as f:
    contents = f.readlines()
    f.close()

# 去除表头
if "股票名称代码" in contents[0]:
    contents.pop(0)

# 初始化数据列表
stock_symbol_list = []
for line in contents:
    line = line.strip().split(",")
    # print(line)
    # 先读取数字
    if line[0].isdigit():
        # 初始化一组新数据，每组6个元素
        this_set = []
        for code in line:
            if code == "":
                break
            code = "%06d" % int(code)
            code_1, code_2 = get_exchange_loc(code)
            this_set.append({"code_1": code_1, "code_2": code_2})
    # 再读取文字
    else:
        for i in range(len(this_set)):
            this_set[i]["name"] = line[i]
        stock_symbol_list += this_set

# 转成 DataFrame 格式
df = pd.DataFrame(stock_symbol_list)
# print(df)
df.to_csv("all_stock_dataframe.csv", encoding="utf-8", index=False)
