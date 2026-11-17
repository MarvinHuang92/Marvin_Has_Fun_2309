# -*- coding: utf-8 -*-

# import game_6nimmt
import os, sys
import random
import game_6nimmt


# 定义可变长度的列表类，元素都是 int， 支持直接对列表本身进行加法运算
# 为什么不是元组类：元组的元素不可以被改写，无法进行加法运算 （'tuple' object does not support item assignment）
class VariableLengthIntList():
    def __init__(self, *init_members):
        # 格式转换：如果输入str，强制转成int
        int_value = []
        for i in init_members:
            int_value.append(int(i))
        self.value = list(int_value)
        self.length = len(self.value)
    
    # 定义加法运算，将两个list的每个元素各自相加
    # 用于赋值运算，相当于 C = A + B
    def add(self, otherVLIlist):
        # 如果两个list长度不同，取两者较小值作为相加的长度
        num = min(self.length, otherVLIlist.length)
        # 复制一个list，防止修改自身
        # ret = self  # 这样不行，会使新的list和旧的值联动
        ret = VariableLengthIntList(*self.value)
        for i in range(num):
            ret.value[i] = self.value[i] + otherVLIlist.value[i]
        return ret

    # 定义自加运算，直接对自身进行操作，无法对外赋值
    # 相当于 A += B
    def add_self(self, otherVLIlist):
        # add方法不会改变自身length，仅改变value，故ret.length = self.length
        ret = self.add(otherVLIlist)
        self.value = ret.value
    
    # 对list中特定的位做加法 A[index] += b
    def add_self_by_index(self, index, add_value):
        self.value[index] += add_value
    
    # 计算list中每个元素的百分比
    def calc_percentage(self, total=0):
        # 允许传入分母，如果不传入，默认用list中所有元素之和作为分母
        if total == 0:
            for i in self.value:
                total += i
        ret = []
        for i in self.value:
            ret.append("%.3f%%" % ((100.0*i)/total))
        
        return ret



def game_result_statistics(csv_input, csv_output, players):
    contents = []
    with open(csv_input) as f:
        contents = f.readlines()
        f.close()
    
    # remove the first line
    contents.pop(0)
    
    game_num = 0
    total_bullheads = VariableLengthIntList(*([0]*players))
    wins = VariableLengthIntList(*([0]*players))
    for line in contents:
        # print(line)
        line_splited = line.split(",")
        # remove first member (game_round)
        line_splited.pop(0)
        # extract the last member (winner)
        winner = line_splited.pop(-1)
        # make the rest members as VLIlsit
        bullheads = VariableLengthIntList(*line_splited)
        # add bullheads of current game into total
        total_bullheads.add_self(bullheads)
        total_bullheads_percentage = total_bullheads.calc_percentage()
        
        # convert winner format: P1 -> 0, P2 -> 1...
        winner_index = int(winner.replace("P", "")) - 1
        # add winner into total
        wins.add_self_by_index(winner_index, 1)
        # wins.value[winner_index] += 1  # 这样也可以，但使用类自带的方法更安全
        wins_percentage = wins.calc_percentage()

        game_num += 1
    
    print("\nTotal games: " + str(game_num))
    print("Bullheads of each player: %s" % str(total_bullheads.value))
    print("Percentage:               %s" % str(total_bullheads_percentage))
    print("Win times of each player: %s" % str(wins.value))
    print("Percentage:               %s" % str(wins_percentage))

    headers = ""
    for i in range(players):
        headers += ("P%d," % (i+1))
    headers = headers.strip(",")
    
    with open(csv_output, "w") as f:
        f.write("---- Total games ----\n")
        f.write("%d\n\n" % game_num)
        f.write("---- Total Bullheads ----\n")
        f.write("%s\n" % headers)
        f.write("%s\n\n" % str(total_bullheads.value).strip("[").strip("]"))
        f.write("---- Total Wins ----\n")
        f.write("%s\n" % headers)
        f.write("%s\n\n" % str(wins.value).strip("[").strip("]"))
        f.close()

def init_record_folder(game_log_folder, game_result_stat_path, players):
    os.system("if not exist %s\\autoplay md %s\\autoplay" % (game_log_folder, game_log_folder))
    os.system("del %s\\autoplay\\*.txt" % game_log_folder)
    os.system("del %s\\autoplay\\nn_sample_data*" % game_log_folder)
    with open(game_result_stat_path, "w") as f:
        f.write("Game_id,")
        for a in range(players):
            f.write("P%s_Bullheads," % str(a+1))
        f.write("Winner\n")
        f.close()

def autorun_game(game_num, players, player_types=None, model_path=None):
    
    # 初始随机种子：100000以内正整数
    init_random_seed = random.randint(1,100000)
    print("\nRandom seed: %d" % init_random_seed)
    
    # python_exe = "python"
    # if os.path.isdir("C:/TCC/Tools/python3/3.7.4-29_WIN64_2"):
    #     python_exe = r"C:\TCC\Tools\python3\3.7.4-29_WIN64_2\python.exe"

    for i in range(game_num):
        # 随机数种子 = 初始随机种子 + 游戏局数
        print("\n==================== Start Game %d =======================" % i)

        # 内部函数调用，速度更快
        game_6nimmt.run_game(players, init_random_seed+i, statistic=True, player_types=player_types, model_path=model_path)
        
        # 外部参数调用，可以打印完整log文件
        # os.system("%s game_6nimmt.py %d %d statistic > game_log\\autoplay\\game_log_%d.txt" % (python_exe, players, init_random_seed+i, init_random_seed+i))

        # 游戏结束
        print("\n=================== Finish Game %d =======================" % i)



if __name__ == "__main__":

    # 用法: python autoplay.py [game_num] [players] [player_types] [model_path]
    # 例如: python autoplay.py 1000 2 "simple_ai,network" model_30.pth

    # 连续进行局数
    GAME_NUM = 1000
    # 玩家数量
    PLAYERS = 2
    # 玩家智能程度（按顺序对应 P1, P2...），不传则全部为 simple_ai
    player_types = None
    # 神经网络玩家使用的模型
    model_path = None

    if len(sys.argv) > 1:
        GAME_NUM = int(sys.argv[1])
    if len(sys.argv) > 2:
        PLAYERS = int(sys.argv[2])
    if len(sys.argv) > 3:
        player_types = [t.strip() for t in sys.argv[3].split(",")]
    if len(sys.argv) > 4:
        model_path = sys.argv[4]

    # 游戏结果的保存位置
    game_log_folder = "game_log"
    game_result_stat_path = game_log_folder + "/00_statistics.csv"
    game_result_summary_path = game_log_folder + "/01_result_summary.csv"

    # 初始化目录和csv统计表
    init_record_folder(game_log_folder, game_result_stat_path, PLAYERS)

    # 自动运行多局游戏
    autorun_game(GAME_NUM, PLAYERS, player_types, model_path)

    # 结果统计
    game_result_statistics(game_result_stat_path, game_result_summary_path, PLAYERS)

