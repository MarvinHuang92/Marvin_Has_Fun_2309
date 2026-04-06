import os
import pandas as pd

# 用于csv原始数据的处理：拆分，拼合

work_dir = r"database\csv_rawdata_full"
newdata_dir = r"database\download_new"
output_dir = r"output\csv_rawdata"

fname_prefix = "history_k_data_"

def convert_date_format(date_str, output_format):
    if output_format == "yyyymmdd":
        date_splited = date_str.split("-")
        output = "%s%02d%02d" % (date_splited[0], int(date_splited[1]), int(date_splited[2]))
    elif output_format == "yyyy-m-d":
        output = "%s-%d-%d" % (date_str[:4], int(date_str[4:6]), int(date_str[6:]))
    # print(output)
    return output

def get_data_properties(data_filename):
    # 如果带有扩展名，需要删掉扩展名
    if ".csv" in data_filename:
        data_filename = data_filename.strip(".csv")
    data_filename = data_filename.replace(fname_prefix, "")
    # print(data_filename)
    f_symbol = ""
    f_start_date = ""
    f_end_date = ""
    error_flag = False
    try:
        f_splited = data_filename.split("_")
        f_symbol = f_splited[0].strip()
        f_start_date = f_splited[1].strip()
        f_end_date = f_splited[2].strip()

        # 转换日期格式
        f_start_date = convert_date_format(f_start_date, output_format="yyyymmdd")
        f_end_date = convert_date_format(f_end_date, output_format="yyyymmdd")
    except:
        error_flag = True
    
    return f_symbol, f_start_date, f_end_date, error_flag


# work_dir 和 newdata_dir中，每只股票的数据只有一份
# 如果有多个数据文件，报出error
def check_duplicate(symbol, dir):
    symbol_hit = 0
    for root, dirs, files in os.walk(dir):
        for f in files:
            f_name, f_extension = os.path.splitext(f)
            # print(f_name, f_extension)
            if f_extension == ".csv":
                # 这里的日期格式为 yyyymmdd，方便直接转成整数
                f_symbol, f_start_date, f_end_date, error_flag = get_data_properties(f_name)
                if error_flag:
                    print('ERROR: the data filename "%s\\%s%s" is invalid!\n' % (dir, f_name, f_extension))
                    exit(-1)
                if f_symbol == symbol:
                    symbol_hit += 1
                    out_s_date = int(f_start_date)
                    out_e_date = int(f_end_date)
                    out_f_name = f

    if symbol_hit == 0:
        print('ERROR: no data of symbol "%s" in dir "%s" was found!\n' % (symbol, dir))
        exit(-1)
    elif symbol_hit > 1:
        print('ERROR: more than 1 data of symbol "%s" in dir "%s" was found!\n' % (symbol, dir))
        exit(-1)
    
    return out_f_name, out_s_date, out_e_date

def remove_index_col(df):
    try:
        data_output = df.drop(["Unnamed: 0"], axis=1)
    except:
        data_output = df
    return data_output

# 拆分数据，注意date以整形传入
def split_dataFrame(data_input, start_date:int, end_date:int, start_offset=0, end_offset=0):
    index = 0
    idx_start = 0
    idx_end = 0
    for d in data_input["date"]:
        index += 1
        d_int = int(convert_date_format(d, output_format="yyyymmdd"))
        # print(index, d_int)
        if start_date <= d_int <= end_date:
            if idx_start == 0:
                idx_start = index
            idx_end = index
    if idx_start == 0:
        print("ERROR: Cannot split data, the date range is not included in original database.\n")
        exit(-1)
    data_output = data_input.iloc[idx_start+start_offset-1:idx_end+end_offset]
    
    return data_output.iloc[:]  # df格式类似list，要避免使用浅copy


def split_rawdata(symbol, start_date, end_date):
    # 检查data文件是否只有一份, 并返回文件名
    input_filename, _, _ = check_duplicate(symbol, work_dir)
    input_filepath = os.path.join(work_dir, input_filename)
    start_d_int = int(convert_date_format(start_date, output_format="yyyymmdd"))
    end_d_int = int(convert_date_format(end_date, output_format="yyyymmdd"))

    # 读取文件：忽略csv注释中的中文编码错误
    data_input = pd.read_csv(input_filepath, encoding="utf_8", encoding_errors="ignore")
    data_output = split_dataFrame(data_input, start_d_int, end_d_int)  # 这里传递的日期为整形

    # 删除可能的空白列
    data_output = remove_index_col(data_output)
    # print(data_output)
    
    # 写入文件，这里的日期为yyyy-m-d格式
    output_filename = "%s%s_%s_%s.csv" % (fname_prefix, symbol, start_date, end_date)
    data_output = data_output.reset_index(drop=True)  # 重置原始索引
    data_output['RowIndex'] = range(len(data_output.iloc[:]))  # 重写新索引列
    data_output.to_csv(os.path.join(output_dir, output_filename), encoding="gbk", index=False)

    print('Data splited successfully: "%s\\%s"\n' % (output_dir, output_filename))

    return data_output


def merge_rawdata(symbol, keep_origin_data=True):
    # 检查data文件是否只有一份, 并返回文件名
    # 这里的日期都是整形，可以参与加减计算
    filename_org, start_date_org, end_date_org = check_duplicate(symbol, work_dir)
    filename_new, start_date_new, end_date_new = check_duplicate(symbol, newdata_dir)
    filepath_org = os.path.join(work_dir, filename_org)
    filepath_new = os.path.join(newdata_dir, filename_new)
    
    # 忽略csv注释中的中文编码错误
    data_org = pd.read_csv(filepath_org, encoding="utf_8", encoding_errors="ignore")
    data_new = pd.read_csv(filepath_new, encoding="utf_8", encoding_errors="ignore")
    # data_merged = pd.concat([data_org, data_new])
    data_merged = data_org.iloc[:0] # 初始化：空的data_merged
    print("\nMerging data: %s" % symbol)
    print("- origin date range:      from %d to %d" % (start_date_org, end_date_org))
    print("- additional date range:  from %d to %d" % (start_date_new, end_date_new))
    # 两份数据的日期不连续，无法拼接
    if start_date_new > end_date_org + 1 or start_date_org > end_date_new + 1:
        print("ERROR: Unable to merge data, due to date range is not continuous.\n")
        exit(-1)
    # 新数据刚好接在原始数据之后，直接拼接
    elif start_date_new == end_date_org + 1:
        data_merged = pd.concat([data_org, data_new])
    # 新数据刚好接在原始数据之前，直接拼接
    elif start_date_org == end_date_new + 1:
        data_merged = pd.concat([data_new, data_org])
    # 有重叠部分：新数据覆盖原始数据
    elif start_date_org >= start_date_new:
        # 新数据在原始数据之前，且两者有重叠部分
        if end_date_org > end_date_new:  
            data_org_splited = split_dataFrame(data_org, end_date_new, end_date_org, 1, 0)
            data_merged = pd.concat([data_new, data_org_splited])
        else: # 新数据的范围完全覆盖原始数据
            data_merged = data_new
    elif start_date_org < start_date_new:
        # 原始数据完全覆盖新数据
        if end_date_org > end_date_new:
            data_org_splited_1 = split_dataFrame(data_org, start_date_org, start_date_new, 0, -1)
            data_org_splited_2 = split_dataFrame(data_org, end_date_new, end_date_org, 1, 0)
            data_merged = pd.concat([data_org_splited_1, data_new])
            data_merged = pd.concat([data_merged, data_org_splited_2])
        else: # 新数据在原始数据之后，且两者有重叠部分
            data_org_splited = split_dataFrame(data_org, start_date_org, start_date_new, 0, -1)
            data_merged = pd.concat([data_org_splited, data_new])
    
    # 删除可能的空白列
    data_merged = remove_index_col(data_merged)
    # print(data_merged)

    output_s_date = min(start_date_org, end_date_org, start_date_new, end_date_new)
    output_e_date = max(start_date_org, end_date_org, start_date_new, end_date_new)
    output_s_date_str = convert_date_format(str(output_s_date), output_format="yyyy-m-d")
    output_e_date_str = convert_date_format(str(output_e_date), output_format="yyyy-m-d")
    data_merged_filename = "%s%s_%s_%s.csv" % (fname_prefix, symbol, output_s_date_str, output_e_date_str)
    data_merged = data_merged.reset_index(drop=True)  # 重置原始索引
    data_merged['RowIndex'] = range(len(data_merged.iloc[:]))  # 重写新索引列
    data_merged.to_csv(os.path.join(work_dir, data_merged_filename), encoding="gbk", index=False)

    print("Data merged successfully: from %d to %d\n" % (output_s_date, output_e_date))

    if not keep_origin_data:
        if not filename_org == data_merged_filename:
            os.remove(filepath_org)


if __name__ == "__main__":
    
    # convert_date_format("20250501", output_format="yyyy-m-d")
    # convert_date_format("20250510", output_format="yyyy-m-d")
    # convert_date_format("20250521", output_format="yyyy-m-d")
    # convert_date_format("20251023", output_format="yyyy-m-d")
    # convert_date_format("20251231", output_format="yyyy-m-d")

    # convert_date_format("2025-5-1", output_format="yyyymmdd")
    # convert_date_format("2025-5-10", output_format="yyyymmdd")
    # convert_date_format("2025-5-21", output_format="yyyymmdd")
    # convert_date_format("2025-10-23", output_format="yyyymmdd")
    # convert_date_format("2025-12-31", output_format="yyyymmdd")
    
    # 测试：拼合数据
    merge_rawdata("sh.000001", keep_origin_data=False)
    merge_rawdata("sh.000002", keep_origin_data=False)
    merge_rawdata("sh.000003", keep_origin_data=False)

    # 测试：拆分数据
    split_rawdata("sh.000001", "2024-5-10", "2024-5-20")
    split_rawdata("sh.000002", "2024-5-10", "2024-5-20")
    split_rawdata("sh.000003", "2024-5-10", "2024-5-20")
    
    