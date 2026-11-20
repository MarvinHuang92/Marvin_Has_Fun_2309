# -*- coding: utf-8 -*-

import random, sys, time, os
import torch  
from neural_network_6nimmt import load_model
from neural_network_run import extra_feature_mode, normalize_state
from policy_6nimmt import load_policy, SCORE_TEMPERATURE

# 策略网络玩家：训练时按概率采样，评测时取 argmax（由 evaluate.py 置 False）
policy_sample = True

# 搜索型玩家（第九轮）：对每个候选动作做若干次随机 rollout，取期望最好的
# 这两个参数可以从环境变量覆盖，方便做对照实验
SEARCH_ROLLOUTS = int(os.environ.get("SEARCH_ROLLOUTS", "12"))
# "diff" = 自己牛头 − 对手牛头（和胜负一致）；"self" = 只看自己的牛头
SEARCH_CRITERION = os.environ.get("SEARCH_CRITERION", "diff")

# 第十一轮：混合型玩家 —— 网络先打分，只对前 K 名做 rollout
HYBRID_TOP_K = int(os.environ.get("HYBRID_TOP_K", "3"))
# 第十二轮：吃行也做搜索（4 个候选行各 rollout 一遍）
HYBRID_ROW_SEARCH = os.environ.get("HYBRID_ROW_SEARCH", "1") not in ("0", "false")
# 第十二轮：自适应 rollout —— 分小批跑，一旦领先幅度超过噪声就提前停
SEARCH_EARLY_STOP = os.environ.get("SEARCH_EARLY_STOP", "1") not in ("0", "false")
# 第十二轮：把网络的先验和 rollout 的代价做收缩混合（0 = 只用 rollout）
#   最终分数 = z(代价) + HYBRID_BLEND * z(网络分数)，两边都按行内标准差归一化
HYBRID_BLEND = float(os.environ.get("HYBRID_BLEND", "0"))
# 第十三轮【诊断专用，不是实战策略】：rollout 时直接偷看对手手牌，量"隐藏信息值多少分"
SEARCH_CHEAT = os.environ.get("SEARCH_CHEAT", "0") not in ("0", "false")
# 老师估值里的那个分母：正确做法是「牌堆大小」（2 人局 24、10 人局 104）。
# 历史代码写死 104，等于在 2 人局把危险度压小了 4 倍多。
# 设 TEACHER_DIVISOR=104 可以完全复现旧行为 —— 用来评估按旧分母训练的模型。
TEACHER_USE_DECK = os.environ.get("TEACHER_DIVISOR", "deck").lower() != "104"

# rollout 里对手的出牌策略：random（默认，对 Lv0 是对的）/ teacher（对强手更接近真实）
OPP_TEACHER = os.environ.get("ROLLOUT_OPP", "random").lower() == "teacher"

# 两阶段搜索的粗筛次数：>0 时先用这么多次 rollout 给全部手牌粗排，再对前 K 名深算
SCREEN_M = int(os.environ.get("HYBRID_SCREEN_M", "0"))


def teacherDivisor(deck_size):
    return float(deck_size) if TEACHER_USE_DECK else 104.0


# 第十四轮【诊断】：rollout 里"我自己"的延续策略（teacher = 手写规则 / random = 乱出）
SEARCH_ROLLOUT_POLICY = os.environ.get("SEARCH_ROLLOUT_POLICY", "teacher")
# L1（价值头早停）：rollout 只往前推这么多回合，剩下的用一个价值估计收尾
#   0 = 不截断（原行为）；1~3 = 截断深度。见 bootstrapValue()
HYBRID_DEPTH = int(os.environ.get("HYBRID_DEPTH", "0"))
# 统计"一共模拟了多少个回合"，用来比较不同配置的算力开销
ROLLOUT_STEPS = [0]
# 统计 bootstrap 被调用了多少次（每次是一次额外的网络前向）
BOOTSTRAP_CALLS = [0]

# 第十轮：把搜索的「逐动作代价」记下来当稠密标签（None = 不记）
# 每条 = state(54) + 14 个动作的代价（非法动作填 0），供 train_policy.py distill_costs 使用
SEARCH_COST_LOG = None
# 诊断用：把 rollout 分成前后两半各记一份，用来量「同一局面下搜索自己会不会改主意」
SEARCH_SPLIT_LOG = None


def recordSearchCosts(state, costs, offset=0):
    """offset: 出牌决策的代价放在 0~9；吃行决策放在 10~13"""
    if SEARCH_COST_LOG is not None:
        row = list(state) + [0.0] * 14
        for i, cost in enumerate(costs):
            row[len(state) + offset + i] = cost
        SEARCH_COST_LOG.append(row)


def normalizeByStd(values):
    """行内按标准差归一化（减去均值、除以标准差），让不同来源的分数可比"""
    n = len(values)
    mean = sum(values) / float(n)
    var = sum((v - mean) ** 2 for v in values) / float(n)
    sd = var ** 0.5
    return [(v - mean) / sd if sd > 1e-9 else 0.0 for v in values]


def pairedConfident(per_rollout, threshold=2.0):
    """成对比较的"已经分出胜负"判断：领先幅度 > threshold 倍标准误就停

    用成对差值（同一批对手手牌下两个动作的代价差）算标准误，比两均值各自的标准误更灵敏。
    """
    n = len(per_rollout)
    if n < 4:
        return False
    means = [sum(column) / float(n) for column in zip(*per_rollout)]
    order = sorted(range(len(means)), key=lambda i: means[i])
    best, second = order[0], order[1]
    diffs = [row[second] - row[best] for row in per_rollout]
    mean_diff = sum(diffs) / float(n)
    sd = (sum((d - mean_diff) ** 2 for d in diffs) / float(n - 1)) ** 0.5
    return mean_diff > threshold * sd / (n ** 0.5)


def cardBullheads(value):
    """与 Card.bullheads 相同的计分规则，供快速模拟使用"""
    if value == 55:
        return 7
    if value % 10 == 5:
        return 2
    if value % 10 == 0:
        return 3
    if value % 11 == 0:
        return 5
    return 1


def bullheadsBetween(lo, hi, deck_size):
    return sum(cardBullheads(v) for v in range(max(1, lo), min(deck_size, hi) + 1))


def teacherPick(rows, hand, deck_size):
    """搜索里用的"我自己后续怎么走"：advanced_ai 的估值规则（简化实现）"""
    ends = [row[-1] for row in rows]
    blanks = [5 - len(row) for row in rows]
    row_bh = [sum(cardBullheads(c) for c in row) for row in rows]
    best_val, best_idx = None, 0
    for idx, card in enumerate(hand):
        positives = [(card - e, i) for i, e in enumerate(ends) if card - e > 0]
        if not positives:
            val = min(row_bh)
        else:
            diff, i = min(positives)
            if diff <= blanks[i]:
                val = 0.0
            else:
                val = row_bh[i] + blanks[i] * bullheadsBetween(ends[i] + 1, card - 1, deck_size) / float(deck_size)
        if best_val is None or val < best_val:
            best_val, best_idx = val, idx
    return hand[best_idx]


def placeCard(rows, value, pick_row, deck_size):
    """按规则把一张牌放进行里（就地修改 rows），返回这一手吃到的牛头

    pick_row(rows) -> 行下标：只在"这张牌比所有行尾都小、必须吃一行"时调用。
    规则：差值最小且为正的那一行；该行满了就吃下整行；否则接到行尾。
    """
    ends = [row[-1] for row in rows]
    diffs = [value - end for end in ends]
    if max(diffs) < 0:                             # 比所有行尾都小，必须吃一行
        target = pick_row(rows)
        taken = sum(cardBullheads(c) for c in rows[target])
        rows[target] = [value]
        return taken
    best_diff, target = None, 0
    for i, diff in enumerate(diffs):
        if diff > 0 and (best_diff is None or diff < best_diff):
            best_diff, target = diff, i
    if len(rows[target]) >= 5:                     # 该行已满，吃下整行
        taken = sum(cardBullheads(c) for c in rows[target])
        rows[target] = [value]
        return taken
    rows[target].append(value)
    return 0


def myRolloutPick(rows, hand, deck_size):
    """rollout 里"我自己"后续怎么走：默认用老师规则，可切成随机（诊断延续策略的重要性）"""
    if SEARCH_ROLLOUT_POLICY == "random":
        return hand[random.randrange(len(hand))]
    return teacherPick(rows, hand, deck_size)


def greedyRow(rows):
    """自己的默认吃行策略：牛头最少的那一行"""
    return min(range(len(rows)), key=lambda i: sum(cardBullheads(c) for c in rows[i]))


def simulateRest(rows, my_hand, opp_hand, my_score, opp_score, first_card, deck_size,
                 first_row_choice=None):
    """从当前局面把剩下的回合打完：我先出 first_card，之后用老师规则；对手全程随机

    first_row_choice：第一回合若我必须吃行，强制吃掉哪一行（吃行搜索用）
    返回 (我的最终牛头, 对手的最终牛头)
    """
    rows = [list(row) for row in rows]
    my, opp = list(my_hand), list(opp_hand)
    me_score, op_score = my_score, opp_score
    for k in range(len(my)):
        mine = first_card if k == 0 else myRolloutPick(rows, my, deck_size)
        theirs = opp[random.randrange(len(opp))]
        for value, is_me in sorted([(mine, True), (theirs, False)]):
            def pick(current, is_me=is_me, k=k):
                if is_me:
                    if k == 0 and first_row_choice is not None:
                        return first_row_choice
                    return greedyRow(current)
                return random.randrange(len(current))
            taken = placeCard(rows, value, pick, deck_size)
            if is_me:
                me_score += taken
            else:
                op_score += taken
        my.remove(mine)
        opp.remove(theirs)
        ROLLOUT_STEPS[0] += 1
    return me_score, op_score


def simulateRestN(rows, my_hand, opp_hands, my_score, opp_scores, first_card, deck_size,
                  opp_teacher=False):
    """N 人局的 rollout：我先出 first_card，之后我按老师规则、对手按 opp_teacher 出牌，打到局末

    opp_teacher=False（默认）：对手随机出牌 —— 对 Lv0 是正确的模型
    opp_teacher=True：对手也按老师规则出牌 —— 对 Lv1/Lv3/人类更接近真实
    和 simulateRest 的区别：每回合要摆 N 张牌（不是 2 张），所以单次模拟的成本约是 2 人局的 N/2 倍。
    返回 (我的总分, 各对手的总分列表)。
    """
    rows = [list(r) for r in rows]
    my = list(my_hand)
    opps = [list(h) for h in opp_hands]
    me = my_score
    ops = list(opp_scores)
    for k in range(len(my)):
        if k == 0 and first_card is not None:
            mine = first_card
        else:
            mine = myRolloutPick(rows, my, deck_size)
        plays = [(mine, -1)]
        picks = []
        for i, h in enumerate(opps):
            if opp_teacher:
                best = myRolloutPick(rows, h, deck_size)
                j = h.index(best) if best in h else random.randrange(len(h))
            else:
                j = random.randrange(len(h))
            plays.append((h[j], i))
            picks.append(j)
        for value, who in sorted(plays):
            def pick(current, who=who):
                return greedyRow(current) if who < 0 else random.randrange(len(current))
            taken = placeCard(rows, value, pick, deck_size)
            if who < 0:
                me += taken
            else:
                ops[who] += taken
        my.remove(mine)
        for i, j in enumerate(picks):
            opps[i].pop(j)
        ROLLOUT_STEPS[0] += 1
    return me, ops


def simulateAfterRow(rows, my_hand, opp_hand, my_score, opp_score, played_card, target_row, deck_size):
    """我已经打出一张"全场最小"的牌、现在要挑一行吃掉时的模拟

    顺序按规则：我先吃掉 target_row（我的牌变成该行的第一张），
    然后对手这一回合的牌才落下，之后打剩下的回合（我用老师规则、对手随机）。
    """
    rows = [list(row) for row in rows]
    me_score = my_score + sum(cardBullheads(c) for c in rows[target_row])
    rows[target_row] = [played_card]

    done = placeCard(rows, opp_hand[0], lambda r: random.randrange(len(r)), deck_size)
    opp_score = opp_score + done

    my, opp = list(my_hand), list(opp_hand[1:])
    for k in range(len(my)):
        mine = myRolloutPick(rows, my, deck_size)
        theirs = opp[random.randrange(len(opp))]
        for value, is_me in sorted([(mine, True), (theirs, False)]):
            def pick(current, is_me=is_me):
                return greedyRow(current) if is_me else random.randrange(len(current))
            taken = placeCard(rows, value, pick, deck_size)
            if is_me:
                me_score += taken
            else:
                opp_score += taken
        my.remove(mine)
        opp.remove(theirs)
        ROLLOUT_STEPS[0] += 1
    return me_score, opp_score


def simulateAfterRowN(rows, my_hand, pending_cards, opp_future_hands, my_score, opp_scores,
                      played_card, target_row, deck_size, opp_teacher=False):
    """N 人局版：我打出全场最小、现在挑一行吃掉

    顺序按规则：我先吃掉 target_row（我的牌成为该行第一张），
    再把**本回合剩下的牌**（`pending_cards`，都是明牌，来自 game.stash）依次落下，
    最后用 N 人 rollout 打完剩下的回合。
    """
    rows = [list(r) for r in rows]
    me = my_score + sum(cardBullheads(c) for c in rows[target_row])
    rows[target_row] = [played_card]
    for v in sorted(pending_cards):
        placeCard(rows, v, lambda r: random.randrange(len(r)), deck_size)
    return simulateRestN(rows, my_hand, opp_future_hands, me, opp_scores, None, deck_size,
                         opp_teacher=opp_teacher)


# ---------------- L1：截断 rollout + 价值头 ----------------
def simulatePartial(rows, my_hand, opp_hand, my_score, opp_score, first_card,
                    deck_size, depth):
    """往前推 depth 个回合就停，返回 (我, 对手, 桌面, 我的手牌)

    depth <= 0 或 >= 手牌数 时推到底（等价于 simulateRest）。
    跟 simulateRest 的区别只是"什么时候停"，其余完全一样。
    """
    rows = [list(r) for r in rows]
    my, opp = list(my_hand), list(opp_hand)
    me, op = my_score, opp_score
    turns = len(my) if depth <= 0 else min(depth, len(my))
    for k in range(turns):
        mine = first_card if k == 0 else myRolloutPick(rows, my, deck_size)
        theirs = opp[random.randrange(len(opp))]
        for value, is_me in sorted([(mine, True), (theirs, False)]):
            def pick(current, is_me=is_me):
                return greedyRow(current) if is_me else random.randrange(len(current))
            taken = placeCard(rows, value, pick, deck_size)
            if is_me:
                me += taken
            else:
                op += taken
        my.remove(mine)
        opp.remove(theirs)
        ROLLOUT_STEPS[0] += 1
    return me, op, rows, my


def teacherScoresFromRows(rows, hand, deck_size):
    """按 advAiCalcPlayCardReward 的公式算逐动作估值（给 bootstrap 拼特征用）

    分母走 teacherDivisor（默认牌堆大小），空位数按 5 列算 —— 必须和引擎里
    advAiCalcPlayCardReward 完全一致，否则网络看到的输入分布就变了。
    """
    ends = [r[-1] for r in rows]
    blanks = [5 - len(r) for r in rows]
    rb = [sum(cardBullheads(c) for c in r) for r in rows]
    div = teacherDivisor(deck_size)
    out = [0.0] * 14                 # 和 calcTeacherFeature 一样：定长 14，前 10 位是手牌估值
    for i, card in enumerate(hand[:10]):
        best_d, idx = None, -1
        for j, e in enumerate(ends):
            d = card - e
            if d > 0 and (best_d is None or d < best_d):
                best_d, idx = d, j
        if idx < 0:
            out[i] = float(min(rb))
        elif best_d <= blanks[idx]:
            out[i] = 0.0
        else:
            out[i] = (rb[idx] + blanks[idx] * bullheadsBetween(ends[idx] + 1, card - 1,
                                                               deck_size) / div)
    return out

# 打分式策略的采样温度（越小越接近贪心）
score_temperature = SCORE_TEMPERATURE

# 是否写「每局一份」的日志/样本；策略采样和评测时只保留总表
PER_GAME_FILES = True

# 训练样本总表（v2 格式：55 列之后追加 5 列元数据，便于离线重算 reward-to-go）
SAMPLE_DATA_MASTER = "game_log/02_nn_sample_data_full_v2.csv"

# 进程启动时间戳 + 对局计数器，用于生成不重复的 game_id
RUN_TIME_TAG = time.strftime("%Y%m%d%H%M%S", time.localtime())
RUN_GAME_COUNTER = 0


class NullFile():
    """评测时用来吞掉文件写入的假文件对象（record_to_file=False）"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def write(self, *args):
        pass

    def writelines(self, *args):
        pass

    def close(self):
        pass

# 用于神经网络训练的样本集，每个回合，每个玩家出牌时，更新一组
# State / Action 在玩家的 playCard() 方法中更新
# Reward 在玩家的 showPenaltyCard() 方法中更新
class NNSampleData():
    def __init__(self):
        # 成员全都是int，格式为：
        ### State ###
        # （舍弃）0-39位：桌面20张牌的数字（偶数位）和牛头数量（奇数位）
        # 0-19位：10张手牌的数字（偶数位）和牛头数量（奇数位）
        # 20-23位：桌面每行剩余空位
        # 24-31位：桌面每行最后一张牌的数字和牛头数量
        # 32-35位：桌面每行牛头总数
        # 36位：玩家数量
        # 37位：剩余手牌数量
        # 38位：当前分数（惩罚牛头数）
        # 39位：决策类型：0-出牌，1-收一整行
        self.state = []
        ### Action ###
        # （舍弃）40位：打出的手牌index（0-9）或收的行数（1-4）
        # 40-49位：打出的手牌index
        # 50-53位：收的行数（1-4）
        # self.action = 0
        self.action = [0]*14
        ### Reward ###
        # 54位：执行动作后的分数（启发式估计值，由 advAiCalc*Reward 算出）
        self.reward = 0
        ### 元数据（v2 新增，55-59位）###
        # 55位：对局编号；56位：第几回合(1-10)；57位：玩家序号(1-based)
        # 58位：本回合真实吃到的牛头；59位：本回合开始前的累计牛头
        # 有了这几列，就能离线把 reward 重算成 reward-to-go / 单步实际罚分，不用重跑对局
        self.game_id = 0
        self.round = 0
        self.seat = 0
        self.penalty_this_round = 0
        self.score_before_round = 0
        # 总表
        self.final_list = []
    
    def calcFinalList(self):
        # self.final_list = self.state + [self.action, self.reward]
        self.final_list = (self.state + self.action + [self.reward]
                           + [self.game_id, self.round, self.seat,
                              self.penalty_this_round, self.score_before_round])


# 定义玩家类
class Player():
    def __init__(self, name):
        self.name = name  # P1, P2...
        self.handCards = []  # 手牌
        self.penaltyCards = []  # 惩罚牌
        self.bullheads = 0  # 惩罚牌的牛头总数（罚分）
        self.played_smallest = False  # 本回合是否出了最小牌，会在每回合playCard之前重置
        # 区分玩家的智能程度 {simple_ai, advanced_ai, human, network}
        self.intellegence = "simple_ai"
        # 用于训练神经网络的指令集，0用于出牌时，1用于打出最小牌后收一整行时
        self.NN_data_0 = NNSampleData()  # 每回合都记录
        self.NN_data_1 = NNSampleData()  # 仅当 played_smallest 时记录
        # 玩家的神经网络模型（若没有神经网络，默认None）
        self.NN_model = None
    
    def sortHandCards(self):
        self.handCards.sort()  # 需要对象支持用 < 操作比较大小

    def showHandCards(self):
        cardlist = ""
        for card in self.handCards:
            cardlist += (str(card.value) + ", ")
        print("%s's HandCards: (%s)" % (self.name, cardlist.strip(", ")))
    
    def showPenaltyCards(self):
        cardlist = ""
        bullheads = 0
        for card in self.penaltyCards:
            cardlist += (str(card.value) + ", ")
            bullheads += card.bullheads
        print("%s's PenaltyCards: (%s), Bullheads: %d" % (self.name, cardlist.strip(", "), bullheads))
        self.bullheads = bullheads  # 将牛头数记录在玩家属性中

        # 更新训练样本集 - Reward
        # 方案1，记录本回合结束时，该玩家“实际”牛头数（回合结束后计算总数）
        # self.NN_data_0.reward = self.bullheads
        # self.NN_data_1.reward = self.bullheads

        # 方案2，采用 Adv Ai 的方法，计算“预期”分数（回合结束前计算delta）
        # 分别在 playCard()，chooseRowWhenSmallest() 方法中执行
    
    # 收集当前场上信息，用于更新 State 样本
    def getGameStateToNNData(self, game, situation=0, cardDeck=None):
        # 桌面牌型
        # state = game.table_data[:]  # 注意list的赋值要加上[:]，否则将成为对原list的引用，无法修改
        state = []  # 暂不添加桌面牌型在前40位
        # 出牌前的手牌
        for card in self.handCards:
            state += [card.value, card.bullheads]
        # 手牌不足10张，补足空位
        for i in range(game.max_round - len(self.handCards)):
            state += [0, 0]
        # 桌面每行剩余空位
        state += self.calcEachRowBlanks(game)
        # 桌面每行最后一张牌的数字和牛头数
        each_row_last_card = self.calcEachRowLastCard(game)
        for last_card in each_row_last_card:
            state += [last_card.value, last_card.bullheads]
        # 桌面每行牛头总数
        state += self.calcEachRowBullheads(game)
        # 玩家人数
        state += [game.players]
        # 出牌前的手牌数
        state += [len(self.handCards)]
        # 出牌前的牛头数
        state += [self.bullheads]
        # print(state)
        
        # 赋值给 NN_data_X，同时加上“场景”状态位
        # 0=出牌时，1=打出最小牌需要收一行时
        # if-else 防止同一回合内 NN_data_1 覆盖了 NN_data_0
        # 额外特征（已出牌集合等）追加在场景位之后
        if normalize_state:
            state = self.normalizeState(state, game)
        extra = self.calcExtraFeatures(game, situation, cardDeck)
        if situation == 0:
            self.NN_data_0.state = (state + [situation] + extra)
        elif situation == 1:
            self.NN_data_1.state = (state + [situation] + extra)

    # state 归一化（第三轮优化）：各类量纲不同（牌号 1~N、牛头 0~7、空位 0~5、人数 2），
    # 直接喂给线性层会让尺度大的几维主导梯度，这里逐段除以各自的上限压到 0~1
    def normalizeState(self, state, game):
        deck_size = float(game.deck_size)
        out = list(state)
        for i in range(0, 20, 2):       # 手牌数字
            out[i] = out[i] / deck_size
        for i in range(1, 20, 2):       # 手牌牛头
            out[i] = out[i] / 7.0
        for i in range(20, 24):         # 每行空位数（0~5）
            out[i] = out[i] / 5.0
        for i in range(24, 32, 2):      # 行尾牌数字
            out[i] = out[i] / deck_size
        for i in range(25, 32, 2):      # 行尾牌牛头
            out[i] = out[i] / 7.0
        for i in range(32, 36):         # 每行牛头总数（5 张牌上限 35）
            out[i] = out[i] / 35.0
        out[36] = out[36] / 10.0        # 玩家数
        out[37] = out[37] / 10.0        # 剩余手牌数
        out[38] = out[38] / 60.0        # 当前罚分
        # 第 39 位是场景位（0/1），不用动
        return out

    # 额外特征（第二轮优化）：把「已出牌集合」这类全局信息编码进 state
    def calcExtraFeatures(self, game, situation=0, cardDeck=None):
        if extra_feature_mode == "none":
            return []
        elif extra_feature_mode == "row_segments":
            return self.calcRowSegmentFeatures(game)
        elif extra_feature_mode == "played_onehot":
            return self.calcPlayedOneHot(game)
        elif extra_feature_mode == "hand_bullheads":
            return self.calcHandBullheadFeatures(game)
        elif extra_feature_mode == "teacher_scores":
            return self.calcTeacherFeature(game, situation, cardDeck, summary=False)
        elif extra_feature_mode == "teacher_summary":
            return self.calcTeacherFeature(game, situation, cardDeck, summary=True)
        else:
            raise ValueError("未知的 extra_feature_mode: %s" % extra_feature_mode)

    # 第七轮方案：把 advanced_ai 的估值公式当**特征**（不是当标签）
    #   逐动作分数（14 维）：出牌时填 0~9（每张手牌一个分），收行时填 10~13（每行牛头）
    #   聚合量（5 维）：最小值 / 均值 / 最好与次好之差 / 分数 <= 0 的个数 / 最大值
    def calcTeacherFeature(self, game, situation, cardDeck, summary):
        scores = [0.0] * 14
        if situation == 0:
            values = [float(item["reward"])
                      for item in self.advAiCalcPlayCardReward(game, cardDeck)]
            for i, v in enumerate(values[:10]):
                scores[i] = v
        elif situation == 1:
            values = [float(v) for v in self.advAiCalcRowReward(game, False)]
            for i, v in enumerate(values[:4]):
                scores[10 + i] = v
        else:
            values = []

        if not summary:
            return scores
        if not values:
            return [0.0] * 5

        ordered = sorted(values)
        margin = (ordered[1] - ordered[0]) if len(ordered) > 1 else 0.0
        return [ordered[0],
                sum(values) / len(values),
                margin,
                float(sum(1 for v in values if v <= 0)),
                ordered[-1]]

    # 方案 A：4 维。用 4 个行尾牌把牌堆切成 4 段，统计每段「已出牌的比例」。
    # 落在这段的牌最终都会贴到「较小的那个行尾」所在行，所以这段越空，往那一行打牌越安全。
    # 注意行尾牌本身不按行号递增，要先排序再切段。
    def calcRowSegmentFeatures(self, game):
        row_ends = sorted(self.calcEachRowLastCardValue(game))
        played = game.played_cards
        features = []
        for i, start in enumerate(row_ends):
            end = row_ends[i + 1] if i + 1 < len(row_ends) else game.deck_size + 1
            width = max(end - start - 1, 1)  # 段内可能出现的牌数
            count = sum(1 for v in played if start < v < end)
            features.append(float(count) / width)
        return features

    # 方案 F（对照组）：N 维 one-hot，直接标记每张牌有没有被打出，信息无损但维度高
    def calcPlayedOneHot(self, game):
        played = set(game.played_cards)
        return [1 if v in played else 0 for v in range(1, game.deck_size + 1)]

    # 第六轮方案（人类玩家的直觉）：3 维
    #   1) 其他人已累计的罚分（2 人局就是对手）
    #   2) 自己手牌的牛头总数
    #   3) 对手手牌里的牛头总数 = 总牛头 - 已打出 - 自己手牌（总牌堆是固定的，所以能算出来）
    def calcHandBullheadFeatures(self, game):
        my_hand = sum(card.bullheads for card in self.handCards)
        others_score = sum(p.bullheads for p in game.playerList if p is not self)
        others_hand = game.deck_total_bullheads - game.played_bullheads - my_hand
        return [others_score, my_hand, others_hand]

    # 策略网络的算法（第四轮）：训练时采样、评测时取 argmax，只考虑合法动作
    def neuronPolicyCalc(self, NN_data, action_list):
        s_i = list(NN_data.state)
        x = torch.Tensor([s_i])
        logits = self.NN_model(x)[0]

        mask = [0.0] * 14
        for a in action_list:
            mask[a] = 1.0
        logits = logits + (torch.Tensor(mask) - 1.0) * 1e9

        if policy_sample:
            probs = torch.softmax(logits, 0)
            return int(torch.multinomial(probs, 1).item())
        return int(torch.argmax(logits).item())

    # 打分式策略（第五轮）：复用 Q 网络（state + 动作 one-hot → 分数），softmax(-分数/温度) 采样
    def scorePolicyScores(self, NN_data, action_list):
        """给给定动作逐个打分（越小越好），不采样"""
        s_i = list(NN_data.state)
        x = torch.Tensor([s_i + [1.0 if i == a else 0.0 for i in range(14)] for a in action_list])
        with torch.no_grad():
            scores = self.NN_model(x).view(-1)
            # 残差结构（第八轮）：最终分数 = alpha * 老师分数 + 网络修正
            if getattr(self.NN_model, "residual", False):
                start, end = self.NN_model.teacher_slice
                teacher = torch.Tensor([NN_data.state[start + a] for a in action_list])
                scores = self.NN_model.alpha * teacher + scores
        return [float(s) for s in scores]

    def neuronScorePolicyCalc(self, NN_data, action_list):
        scores = torch.Tensor(self.scorePolicyScores(NN_data, action_list))
        logits = -scores / score_temperature

        if policy_sample:
            probs = torch.softmax(logits, 0)
            return int(torch.multinomial(probs, 1).item())
        return int(torch.argmax(logits).item())

    # 这个座位每个候选做多少次 rollout：优先用实例上的 rollout_count，否则用全局
    #   —— 有了它，同一局里可以让 search 用 8 次、hybrid 用 24 次，各取所需
    def rolloutCount(self):
        n = getattr(self, "rollout_count", None)
        return SEARCH_ROLLOUTS if n is None else int(n)

    # 这个座位剪枝留几个候选：优先实例上的 hybrid_k，否则用全局
    def hybridK(self):
        n = getattr(self, "hybrid_k", None)
        return HYBRID_TOP_K if n is None else int(n)

    # 这个座位的评价准则：优先实例上的 criterion，否则用全局
    #   diff = 我 − 各对手平均（默认）；max = 我 − 最强的对手；self = 只看我自己
    def criterion(self):
        return getattr(self, "search_criterion", None) or SEARCH_CRITERION

    # rollout 里的对手是否按老师规则出牌
    def oppTeacher(self):
        v = getattr(self, "opp_teacher", None)
        return OPP_TEACHER if v is None else bool(v)

    # 两阶段搜索的粗筛次数（0 = 不用两阶段）
    def screenM(self):
        n = getattr(self, "screen_m", None)
        return SCREEN_M if n is None else int(n)

    # 把 rollout 结果折成一个"越小越好"的代价
    # 2 人局时 ops 只有一个元素，diff 和 max 都退化成 me - op，和老代码完全等价
    def criterionCost(self, me, ops):
        mode = self.criterion()
        if mode == "self" or not ops:
            return me
        if mode == "max":
            return me - max(ops)
        return me - sum(ops) / float(len(ops))

    # L1：本局的 rollout 截断深度。返回 0 表示不截断
    #   优先用实例上的 search_depth（对照实验里两个座位可以不同），否则用全局 HYBRID_DEPTH。
    #   只有「带模型 + diff 准则 + teacher_scores 特征」时才能 bootstrap，
    #   因为 Q 是 diff 单位、而且输入维度要跟训练时一致。
    def rolloutDepth(self):
        d = getattr(self, "search_depth", None)
        if d is None:
            d = HYBRID_DEPTH
        if d <= 0 or self.NN_model is None or SEARCH_CRITERION == "self":
            return 0
        if extra_feature_mode != "teacher_scores":
            return 0
        return d

    # L1：截断 rollout 的叶子价值 —— 用打分网络估 min_a Q(s, a)
    #   Q 是「搜索蒸馏」出来的逐动作代价，单位就是 diff（我 − 对手），
    #   所以它可以直接接到「me - op」这个代价后面
    def bootstrapValue(self, rows, hand, my_score, players, deck_size):
        if not hand:
            return 0.0
        ends = [r[-1] for r in rows]
        state = []
        for i in range(10):                      # 手牌（不足补 0）
            if i < len(hand):
                state += [hand[i], cardBullheads(hand[i])]
            else:
                state += [0, 0]
        state += [5 - len(r) for r in rows]      # 每行空位
        for i in range(4):                       # 行尾牌
            state += [ends[i], cardBullheads(ends[i])]
        state += [sum(cardBullheads(c) for c in r) for r in rows]   # 每行牛头
        state += [players, len(hand), my_score, 0]                  # 场景位 0 = 出牌
        state += teacherScoresFromRows(rows, hand, deck_size)       # 老师估值特征
        legal = list(range(len(hand)))
        x = [state + [1.0 if j == a else 0.0 for j in range(14)] for a in legal]
        with torch.no_grad():
            q = self.NN_model(torch.Tensor(x)).view(-1)
        BOOTSTRAP_CALLS[0] += 1
        return float(q.min())

    # 搜索型玩家（第九轮）：对给定候选动作做 SEARCH_ROLLOUTS 次 rollout，返回每个候选的平均代价
    # 注意：对手手牌是隐藏信息，这里从「未见过的牌」里随机采样一副，而不是偷看真实手牌
    # 公共随机数：同一批对手手牌喂给所有候选动作，动作之间的差值才可比、噪声才小
    def searchCostsFor(self, game, candidate_indexes, rounds=None):
        rows = [[c.value for c in row if c] for row in game.table]
        my_hand = [c.value for c in self.handCards]
        played = set(game.played_cards)
        unseen = [v for v in range(1, game.deck_size + 1)
                  if v not in played and v not in my_hand]
        opp_score = sum(p.bullheads for p in game.playerList if p is not self)
        n_players = len(game.playerList) if game.playerList else game.players

        rounds = rounds or self.rolloutCount()
        opp_sets = None
        if n_players > 2:
            # N 人局：每回合要摆 N 张牌，单次模拟成本约是 2 人局的 N/2 倍。
            # 对手牌全从「未见过的牌」里采（不偷看），一次采够 N-1 家。
            need = (n_players - 1) * len(my_hand)
            opp_scores = [p.bullheads for p in game.playerList if p is not self]
            opp_sets = []
            for _ in range(rounds):
                pool = random.sample(unseen, min(need, len(unseen)))
                while len(pool) < need:            # 极少见：兜底补齐
                    pool.append(random.choice(unseen))
                h = len(my_hand)
                opp_sets.append([pool[i * h:(i + 1) * h] for i in range(n_players - 1)])
        elif SEARCH_CHEAT:      # 诊断：直接知道对手的真实手牌（真实对局不可能，只为量上界）
            true_hand = next([c.value for c in p.handCards]
                             for p in game.playerList if p is not self)
            # 对手可能已经打出本回合的牌（还没结算），那张牌确实未知 -> 从未知牌里补一张
            spare = [v for v in unseen if v not in true_hand]
            while len(true_hand) < len(my_hand) and spare:
                true_hand.append(spare.pop(0))
            opp_hands = [list(true_hand) for _ in range(rounds)]
        else:
            opp_hands = [random.sample(unseen, len(my_hand)) for _ in range(rounds)]
        per_rollout = []
        batch = max(2, rounds // 4)
        depth = self.rolloutDepth() if n_players <= 2 else 0   # L1 只做了 2 人版
        for t in range(rounds):
            row = []
            for idx in candidate_indexes:
                if n_players > 2:
                    me, ops = simulateRestN(rows, my_hand, opp_sets[t], self.bullheads,
                                            opp_scores, my_hand[idx], game.deck_size,
                                            opp_teacher=self.oppTeacher())
                    row.append(self.criterionCost(me, ops))
                elif depth > 0:
                    # L1：只推 depth 个回合，剩下的用 min_a Q(s,a) 收尾
                    me, op, r2, h2 = simulatePartial(rows, my_hand, opp_hands[t], self.bullheads,
                                                     opp_score, my_hand[idx],
                                                     game.deck_size, depth)
                    leaf = self.bootstrapValue(r2, h2, me, game.players, game.deck_size)
                    row.append(me - op + leaf)
                else:
                    me, op = simulateRest(rows, my_hand, opp_hands[t], self.bullheads, opp_score,
                                          my_hand[idx], game.deck_size)
                    row.append(self.criterionCost(me, [op]))
            per_rollout.append(row)
            # 自适应预算：小批跑完就能分出胜负就不再浪费 rollout
            if (SEARCH_EARLY_STOP and len(candidate_indexes) > 1 and len(per_rollout) >= 2 * batch
                    and len(per_rollout) % batch == 0 and pairedConfident(per_rollout)):
                break
        used = len(per_rollout)
        costs = [sum(column) / float(used) for column in zip(*per_rollout)]

        for idx, cost in zip(candidate_indexes, costs):
            self.search_costs[my_hand[idx]] = cost
        if SEARCH_SPLIT_LOG is not None and used >= 4 and len(candidate_indexes) > 1:
            half = used // 2
            first = [sum(c) / float(half) for c in zip(*per_rollout[:half])]
            second = [sum(c) / float(used - half) for c in zip(*per_rollout[half:])]
            SEARCH_SPLIT_LOG.append(([my_hand[i] for i in candidate_indexes],
                                     first.index(min(first)),
                                     second.index(min(second)),
                                     min(sorted(costs)[1:]) - min(costs)))
        return costs

    def chooseCardBySearch(self, game, cardDeck):
        self.search_costs = {}
        costs = self.searchCostsFor(game, list(range(len(self.handCards))))
        recordSearchCosts(self.NN_data_0.state, costs)
        return costs.index(min(costs))

    # 混合型玩家（第十一轮）：网络给所有手牌打分，只把前 K 名交给 rollout
    # 网络负责"别浪费预算在明显差的牌上"，搜索负责"在前几名里挑真的更好的那张"
    def chooseCardByHybrid(self, game, cardDeck):
        self.search_costs = {}
        legal = list(range(len(self.handCards)))
        scores = self.scorePolicyScores(self.NN_data_0, legal)
        ranked = [a for _, a in sorted(zip(scores, legal))]
        k = max(1, self.hybridK())
        if self.screenM() > 0 and len(legal) > k:
            # 两阶段：先用便宜 rollout 给全部手牌粗排（网络排序偶尔会漏掉最优牌），
            # 再只对粗排前 k 名做深算
            coarse = self.searchCostsFor(game, legal, rounds=self.screenM())
            order = sorted(range(len(legal)), key=lambda i: coarse[i])
            candidates = [legal[i] for i in order[:k]]
        else:
            candidates = ranked[:k]
        costs = self.searchCostsFor(game, candidates)
        if HYBRID_BLEND > 0 and len(candidates) > 1:
            # 网络先验 + rollout 代价的收缩混合：rollout 只有几十次采样，噪声不小，
            # 掺一点网络的相对排序能把"其实差不多"的动作拉回来
            network = dict(zip(legal, scores))
            z_cost = normalizeByStd(costs)
            z_net = normalizeByStd([network[a] for a in candidates])
            combined = [c + HYBRID_BLEND * n for c, n in zip(z_cost, z_net)]
            return candidates[combined.index(min(combined))]
        return candidates[costs.index(min(costs))]

    # 第十二轮：吃行也搜索 —— 4 个候选行各做一遍 rollout
    # 吃掉一行会把那一行清空并让我的牌成为新的行首，影响后面所有回合，所以值得算
    def chooseRowBySearch(self, game, card):
        rows = [[c.value for c in row if c] for row in game.table]
        my_hand = [c.value for c in self.handCards]
        n_players = len(game.playerList) if game.playerList else game.players
        rounds = self.rolloutCount()
        costs = []

        if n_players > 2:
            # 本回合还没结算的牌都是明牌（在 game.stash 里，且都比我的牌大）
            pending = [it["card"].value for it in game.stash if it["card"].value > card.value]
            played = set(game.played_cards) | set(pending)
            unseen = [v for v in range(1, game.deck_size + 1)
                      if v not in played and v not in my_hand]
            opp_scores = [p.bullheads for p in game.playerList if p is not self]
            need = (n_players - 1) * len(my_hand)
            hand_sets = []
            for _ in range(rounds):
                pool = random.sample(unseen, min(need, len(unseen)))
                while len(pool) < need:
                    pool.append(random.choice(unseen))
                h = len(my_hand)
                hand_sets.append([pool[i * h:(i + 1) * h] for i in range(n_players - 1)])
            for target in range(len(rows)):
                total = 0.0
                for S in hand_sets:
                    me, ops = simulateAfterRowN(rows, my_hand, pending, S, self.bullheads,
                                                opp_scores, card.value, target,
                                                game.deck_size, self.oppTeacher())
                    total += self.criterionCost(me, ops)
                costs.append(total / float(rounds))
            return costs.index(min(costs))

        # 2 人局：保持原样（不要动，之前所有 2 人局数字都依赖这条路径）
        played = set(game.played_cards)
        unseen = [v for v in range(1, game.deck_size + 1)
                  if v not in played and v not in my_hand]
        opp_score = sum(p.bullheads for p in game.playerList if p is not self)
        # 吃行时我已打出本回合的牌（手牌 n-1 张），对手手上还有 n 张未知的牌
        # （n-1 张手牌 + 本回合已打出但还没结算的那张），所以采样 n 张
        opp_hands = [random.sample(unseen, len(my_hand) + 1) for _ in range(rounds)]
        for target in range(len(rows)):
            total = 0.0
            for opp_hand in opp_hands:
                me, op = simulateAfterRow(rows, my_hand, opp_hand, self.bullheads, opp_score,
                                          card.value, target, game.deck_size)
                total += self.criterionCost(me, [op])
            costs.append(total / float(rounds))
        return costs.index(min(costs))

    def playCard(self, game, cardDeck):
        # 收集 State 信息
        self.getGameStateToNNData(game, 0, cardDeck)

        # 选择出哪张牌
        card, index, handcards_dicts = self.chooseCardToPlay(game, cardDeck)
        self.handCards.pop(index)
        print("%s plays %s. (index: %d)" % (self.name, card.name, index))
        game.stash.append({"player":self, "card":card})
        
        # 将出牌的脚标加入 Action 样本集
        action_list = [0]*14
        action_list[index] = 1
        action_list_invalid = [-1] + [0]*13
        if not self.intellegence == "network":
            self.NN_data_0.action = action_list
        else:
            self.NN_data_0.action = action_list_invalid  # 如果玩家是神经网络，用-1标记，后续不会加入样本集
        
        # 记录 Reward 样本集
        self.NN_data_0.reward = handcards_dicts[index]["reward"]

    # 玩家思考该出哪张牌
    def chooseCardToPlay(self, game, cardDeck):
        # 计算每张手牌的预期分数
        display = False
        if self.intellegence == "advanced_ai":
            display = True
        handcards_dicts = self.advAiCalcPlayCardReward(game, cardDeck, display)

        # 普通电脑
        if self.intellegence == "simple_ai":
            index = random.randint(0, game.left_round)  # 随机出一张牌
        # 高级电脑
        elif self.intellegence == "advanced_ai":
            # 针对reward排序
            handcards_dicts = sorted(handcards_dicts, key = lambda i: i["reward"])
            # 打出reward最低的牌
            # 可能有相同 reward 情况，当前先不考虑更细分的优先级，注释中有描述，算法后面再补充
            card = handcards_dicts[0]["card"]
            index = self.handCards.index(card)
        # 人类玩家
        elif self.intellegence == "human":
            # 最后一局，不必询问
            if game.left_round == 0:
                return self.handCards[0], 0
            # 手牌多于一张，提示玩家选牌
            else:
                self.showHandCards()
                while True:
                    a = input("%s: Please choose a card to play..." % self.name)
                    for card in self.handCards:
                        if str(card.value) == a:
                            index = self.handCards.index(card)
                            return card, index
        # 神经网络
        elif self.intellegence == "network":
            self.showHandCards()
            # 列出所有可能的action
            action_list = []
            for i in range(len(self.handCards)):
                action_list.append(i)  # 手牌的脚标，0-9
            # 计算最优 action
            index = self.neuronNetworkCalc(self.NN_data_0, action_list)
        # 策略网络（第四轮）
        elif self.intellegence == "policy":
            action_list = list(range(len(self.handCards)))
            index = self.neuronPolicyCalc(self.NN_data_0, action_list)
        # 打分式策略（第五轮）
        elif self.intellegence == "scorepolicy":
            index = self.neuronScorePolicyCalc(self.NN_data_0, list(range(len(self.handCards))))
        # 搜索型玩家（第九轮）
        elif self.intellegence == "search":
            index = self.chooseCardBySearch(game, cardDeck)
            # 第十轮：把启发式 reward 换成搜索算出的逐动作代价（样本里的标签因此变准）
            for item in handcards_dicts:
                item["reward"] = self.search_costs.get(item["card"].value, item["reward"])
        # 混合型玩家（第十一轮）：网络剪枝 + 前 K 名 rollout
        elif self.intellegence == "hybrid":
            index = self.chooseCardByHybrid(game, cardDeck)
        # GBDT（树集成对照实验）：输入拼法与 Q 网络完全一样，只把函数族从 MLP 换成树
        elif self.intellegence == "gbm":
            action_list = list(range(len(self.handCards)))
            index = self.neuronGBMCalc(self.NN_data_0, action_list)

        return self.handCards[index], index, handcards_dicts 
        

    # 当打出最小牌时，选择收哪一行
    def chooseRowWhenSmallest(self, game, card):
        # 更新 State 样本集，场景=1（收一整行）
        self.played_smallest = True
        self.getGameStateToNNData(game, situation=1)
        
        # 计算回收每行的预期分数
        display = False
        if self.intellegence == "advanced_ai":
            display = True
        bullheads_list = self.advAiCalcRowReward(game, display)

        # 普通电脑，随机收一行
        if self.intellegence == "simple_ai":
            ret = random.randint(1,4)
        # 高级电脑：计算每一行牛头数，收牛头最少的，如果并列，收靠前的行
        elif self.intellegence == "advanced_ai":
            ret = bullheads_list.index(min(bullheads_list)) + 1
        # 人类玩家
        elif self.intellegence == "human":
            while True:
                a = input("%s: You played a smallest card! (%s) Please choose a row to clean... (1,2,3,4)" % (self.name, card.name))
                for r in range(1,5):
                    if str(r) == a:
                        ret = r
                        break
        # 神经网络
        elif self.intellegence == "network":
            # 列出所有可能的action
            # action_list = [1,2,3,4]  # 要收牌的行号，注意从1开始
            action_list = [10,11,12,13]  # 要收牌的行号，1-4行对应 action 脚标 10-13
            # 计算最优 action，注意结果也要+1
            ret = self.neuronNetworkCalc(self.NN_data_1, action_list) + 1
        # 策略网络（第四轮）：返回值是 10~13，转成 1~4
        elif self.intellegence == "policy":
            ret = self.neuronPolicyCalc(self.NN_data_1, [10, 11, 12, 13]) - 9
        # 打分式策略（第五轮）
        elif self.intellegence == "scorepolicy":
            ret = self.neuronScorePolicyCalc(self.NN_data_1, [10, 11, 12, 13]) + 1
        # 搜索型玩家（第九轮）：吃行直接选牛头最少的一行（这一步的搜索收益很小）
        elif self.intellegence == "search":
            ret = bullheads_list.index(min(bullheads_list)) + 1
            recordSearchCosts(self.NN_data_1.state, bullheads_list, offset=10)
        # 混合型玩家（第十一轮）：吃行和搜索型保持一致，好把差别只归到"出牌选择"上
        # 第十二轮：改成也搜索 —— 4 个候选行各 rollout 一遍（HYBRID_ROW_SEARCH=0 可关掉）
        elif self.intellegence == "hybrid":
            if HYBRID_ROW_SEARCH:
                ret = self.chooseRowBySearch(game, card) + 1
            else:
                ret = bullheads_list.index(min(bullheads_list)) + 1
        # GBDT（树集成对照）
        elif self.intellegence == "gbm":
            ret = self.neuronGBMCalc(self.NN_data_1, [10, 11, 12, 13]) + 1
        
        # 更新 Action 样本集
        action_list = [0]*14
        action_list[10+ret-1] = 1
        action_list_invalid = [-1] + [0]*13
        if not self.intellegence == "network":
            self.NN_data_1.action = action_list
        else:
            self.NN_data_1.action = action_list_invalid  # 如果玩家是神经网络，用-1标记，后续不会加入样本集

        # 记录 Reward 样本集
        self.NN_data_1.reward = bullheads_list[ret - 1]

        return ret

    # 高级电脑的算法

    # 计算每张手牌的预期分数
    def advAiCalcPlayCardReward(self, game, cardDeck, display=False):
        # 读取每行的空位数量
        each_row_blanks = self.calcEachRowBlanks(game)
        # 读取每行最后一张牌
        each_row_last_card_value = self.calcEachRowLastCardValue(game)
        # 读取每行的牛头总数
        bullheads_list = self.calcEachRowBullheads(game)

        # 策略：遍历手牌，计算每张手牌的预期分值
        # 场上每行最大的牌 0       1       2       3
        #                |       |       |       |
        # 手牌      0   1   2   3   4   5   6   7   8   9
        #                |       |       |       |
        #     smallest   |safe|X |safe|X |safe|X |safe|X

        handcards_dicts = []
        for handcard in self.handCards:
            # 计算“最小的正差值”以确定手牌会被放进哪一行
            closest_positive_diff = 0
            closest_row_index = 0
            for i in range(4):
                diff = handcard.value - each_row_last_card_value[i]
                if (diff > 0) and \
                    (not closest_row_index or (closest_row_index and (diff < closest_positive_diff))):
                    closest_positive_diff = diff
                    closest_row_index = i + 1
            # 0. smallest：手牌 < min(每行最大牌)，预期分值=场上所有行的牛头最小值，
            #    可能不止一张，预期分值小时，先出小牌，反之先出大牌（尽量搭别人便车） 
            if not closest_row_index:
                handcards_dicts.append({"card": handcard, "class": "smallest", "reward": min(bullheads_list)})
            else:
                # 1. safe：0 < 手牌-某行最大牌 <= 该行空位数，绝对安全，分值=0，
                #    组内优先级：1.手牌距离场上牌最近的 2.该行空位少的 3.先出小牌（大的那行不容易被人占）
                # 1A. 0 < 手牌-某行最大牌 <= 该行空位数+两者之间曾出现过的牌数量，同上（算法后续补充）
                if closest_positive_diff <= each_row_blanks[closest_row_index-1]:
                    handcards_dicts.append({"card": handcard, "class": "safe", "target_row": closest_row_index, "reward": 0})
                # 2. X(danger)：预期分值 = 该行已有牛头数 + 空格数 × 两牌之间的牛头数 / 牌堆大小
                #    （分母应该是牌堆大小：2 人局 24、10 人局 104；历史上写死 104，见 teacherDivisor）
                else:
                    reward_exp = (bullheads_list[closest_row_index - 1]
                                  + each_row_blanks[closest_row_index - 1]
                                  * float(cardDeck.calcBullheadsBetween(
                                      each_row_last_card_value[closest_row_index - 1] + 1,
                                      handcard.value - 1))
                                  / teacherDivisor(game.deck_size))
                    handcards_dicts.append({"card": handcard, "class": "danger", "target_row": closest_row_index, "reward": reward_exp})
        
        if display:
            self.showHandCards()
            print("\n" + self.name + ": Expected reward of each handcard:")
            for item in handcards_dicts:
                print(item["reward"])
            print("")

        return handcards_dicts

    # 计算回收每行的预期分数
    def advAiCalcRowReward(self, game, display):
        bullheads_list = self.calcEachRowBullheads(game)
        if display:
            print("\n" + self.name + ": Bullheads of each row: " + str(bullheads_list) + "\n")
        return bullheads_list

    def calcEachRowBlanks(self, game):
        each_row_blanks = []
        for row in range(4):
            blanks = 0
            for col in game.table[row]:
                if not col:
                    blanks += 1
            each_row_blanks.append(blanks)
        return each_row_blanks

    def calcEachRowLastCard(self, game):
        each_row_last_card = []
        for row in range(4):
            last_card = None
            for col in game.table[row]:
                if col:
                    last_card = col
            each_row_last_card.append(last_card)
        return each_row_last_card

    def calcEachRowLastCardValue(self, game):
        each_row_last_card = self.calcEachRowLastCard(game)
        each_row_last_card_value = []
        for last_card in each_row_last_card:
            each_row_last_card_value.append(last_card.value)
        return each_row_last_card_value
    
    def calcEachRowBullheads(self, game):
        bullheads_list = []
        for row in range(4):
            bullheads = 0
            for col in game.table[row]:
                if col:
                    bullheads += col.bullheads
            bullheads_list.append(bullheads)
        return bullheads_list

    # 神经网络的算法
    def neuronNetworkCalc(self, NN_data, action_list):
        # 提供神经网络的输入
        x_list = []
        s_i = list(NN_data.state)  # 当前state信息
        # print(s_i)
        # a_list = []
        for a in action_list:  # 这里的a是真正的action_list的脚标
            real_action_list = [0]*14
            real_action_list[a] = 1
            x_i = s_i + real_action_list  # x_i = state + 每种可能的action
            x_list.append(x_i)
            # a_list.append(real_action_list)
        x = torch.Tensor(x_list)  # 将x由二维list转为二维张量
        # print(x)

        # 显示所有可能action的向量形式
        # print("\n" + self.name + "'s possible actions:\n" + str(a_list[:]) + "\n")

        # 使用 model 预测结果 h, 表示每一种action对应的预测reward
        h = self.NN_model(x).data   #.data()可以提取张量部分，舍弃梯度函数部分
        print("\n" + self.name + "'s neural network output:\n" + str(h[:]) + "\n")
        
        # 将张量 h 变形为 list
        h_list = []
        for h_i in h:  # 将二维张量拆解成一维
            h_list.append(h_i[0].item())  #.item()将一维张量转为数值
        # print(h_list)
            
        # 输出预测reward（罚分）最小的action
        return h_list.index(min(h_list))

    # GBDT 的算法（树集成对照）：输入拼法与 neuronNetworkCalc 完全一致
    def neuronGBMCalc(self, NN_data, action_list):
        s_i = list(NN_data.state)
        x_list = []
        for a in action_list:
            real_action_list = [0] * 14
            real_action_list[a] = 1
            x_list.append(s_i + real_action_list)
        scores = list(self.NN_model.predict(x_list))
        return scores.index(min(scores))


# 定义“牌”类
class Card():
    def __init__(self, value):
        self.name = "Card_" + str(value)
        self.value = value
        self.bullheads = 1
        if value == 55:
            self.bullheads = 7
        elif value % 10 == 5:
            self.bullheads = 2
        elif value % 10 == 0:
            self.bullheads = 3
        elif value % 11 == 0:
            self.bullheads = 5
    
    # 重载比较操作符"<"，用于比较类成员大小
    def __lt__(self, other):
        if self.value < other.value:
            return True
        else:
            return False
    
    def showInfo(self):
        print("%s, Bullheads: %d" %(self.name, self.bullheads))


# 定义“牌堆”类，继承自列表类
class CardDeck(list):
    def __init__(self, players=10):
        # 创建104张牌对象 
        # for i in range(1, 105):
        # 创建"玩家数量*10+4"张牌，玩家数默认10个
        for i in range(1, players*10+5):
            exec("Card_%d = Card(%d)" %(i, i))  # 需要创建新变量时，用 exec，否则可以用 exec 或 eval
            eval("self.append(Card_%d)" %i)
        # 备份 “影子牌堆” 防止被打乱顺序
        self.shadow = self[:]
        # 常量：所有牌的牛头数 = 171
        # self.total_bullheads = self.calcBullheadsBetween(1 , 104)

    # 显示牌堆顺序
    def showCards(self):
        cardlist = ""
        for card in self:
            cardlist += (str(card.value) + ", ")
        print("CardDeck: (%s)" % cardlist.strip(", "))

    # 计算任意两张牌之间的牛头数量，包含输入两端的牌
    def calcBullheadsBetween(self, start, end):
        bullheads = 0
        for card in self.shadow[start-1 : end]:
            bullheads += card.bullheads
        return bullheads


# 定义“游戏”类
class Game():
    # ====================
    # [0,0] | ... | [0,4]
    #  ...  | ... |  ...
    # [3,0] | ... | [3,4]
    # ====================
    def __init__(self, players, rounds=10):
        # 定义桌面（4*5网格）
        # self.table = [[None,]*5]*4  # 这样生成的4行会产生联动，不行
        self.table = [None,]*5, [None,]*5, [None,]*5, [None,]*5

        # 定义缓存区，存放玩家一回合中打出的牌
        # 其中元素示例 {"player":P1, "card":Card_1}
        self.stash = []
        # 当前桌面牌型的 NN_data 样本集格式（前40位）
        self.table_data = []
        # 游戏玩家数
        self.players = players
        # 牌堆大小（每人 10 张 + 4 张底牌）
        self.deck_size = players * 10 + 4
        # 已经打出去的牌（含开局 4 张底牌），用于「已出牌集合」类特征
        self.played_cards = []
        # 已打出牌的牛头总数（含被吃掉的），用于「手牌牛头」类特征
        self.played_bullheads = 0
        # 这副牌的总牛头数（创建牌堆后由 run_game 填），用于推算对手手牌
        self.deck_total_bullheads = 0
        # 玩家列表（run_game 里填），用于读取其他玩家的分数
        self.playerList = []
        # 总回合数，默认10
        self.max_round = rounds
        # 剩余回合数，默认10-1
        self.left_round = rounds - 1
    
    # 整理打出的牌（每回合结算）
    def arrangeCard(self):
        print("Sorting Cards...")
        self.stash = sorted(self.stash, key = lambda i: i["card"])
        for item in self.stash:
            # 这张牌已经出场（之后要么进某一行，要么被吃掉），记录下来
            self.played_cards.append(item["card"].value)
            self.played_bullheads += item["card"].bullheads
            # 计算当前牌与每行最后一张牌的差值
            diffs = []
            for row in range(4):
                for col in self.table[row]:
                    if col:
                        last_card_value = col.value
                    else:
                        break
                diffs.append(item["card"].value-last_card_value)
            # 如果是场上最小的牌，玩家自行选择清除一行
            if max(diffs) < 0:
                target_row = item["player"].chooseRowWhenSmallest(self, item["card"])
                print(item["player"].name + " plays " + item["card"].name + ", it is the smallest card! cleaned row %d as %s's Penalty." % (target_row, item["player"].name))
                # 传入的参数为 1-4 行，转换为脚标 0-3
                row = target_row - 1
                for i in range(5):
                    if self.table[row][i]:
                        item["player"].penaltyCards.append(self.table[row][i])
                        self.table[row][i] = None
                self.table[row][0] = item["card"]
            # 不是最小的牌，按照规则放在正确的行
            else:
                last_d = 104  # 当总牌数小于104时，该算法不受影响
                for d in diffs:
                    if 0 < d < last_d:
                        last_d = d
                        target_row = diffs.index(d)+1
                
                # 传入的参数为 1-4 行，转换为脚标 0-3
                row = target_row - 1
                # 显示信息
                print("%s puts %s to Row %d." % (item["player"].name, item["card"].name, target_row))
                # 该行有空位
                if None in self.table[row]:
                    for col in self.table[row]:
                        if not col:
                            self.table[row][self.table[row].index(col)] = item["card"]
                            break
                # 该行已满
                else:
                    print("Row %d is full, cleaned this row as %s's Penalty." % (target_row, item["player"].name))
                    for i in range(5):
                        item["player"].penaltyCards.append(self.table[row][i])
                        self.table[row][i] = None
                    self.table[row][0] = item["card"]
     
    def showTable(self):
        toDisplayNN = []
        print("Show Table...")
        for row in self.table:
            toDisplay = "| "
            for col in row:
                if col:
                    toDisplay += (("%3d(%d)" % (col.value, col.bullheads)) + "| ")
                    toDisplayNN += [col.value, col.bullheads]
                else:
                    toDisplay += "      | "
                    toDisplayNN += [0, 0]
            print(toDisplay)
        # 返回桌面牌型，用于训练样本集的输入
        return toDisplayNN
    
    def leftRoundDecrement(self):
        print("Current_Round_left: %d" % self.left_round)
        self.left_round -= 1


# 游戏主进程
# player_types: 每个玩家的智能程度，可选 simple_ai / advanced_ai / human / network
#               不传时全部为 simple_ai（普通电脑，随机出牌）
# model_path:   神经网络玩家加载的模型文件，不传时使用 neural_network_run.py 中的 model_path
# record_to_file: 是否写对局日志/训练样本；评测时可以关掉，避免污染训练集
# 返回：{"bullheads": [各玩家罚分], "winner": 胜者脚标(0-based)}
def run_game(players, random_seed, statistic, player_types=None, model_path=None,
             record_to_file=True, player_opts=None):

    # 玩家数量 (2-10)
    PLAYERS = players
    # 每人手牌数 = 回合数，默认10
    HANDCARDS = 10

    if player_types is None:
        player_types = ["simple_ai"] * PLAYERS
    if len(player_types) != PLAYERS:
        raise ValueError("player_types 数量(%d)与玩家数(%d)不一致" % (len(player_types), PLAYERS))

    global RUN_GAME_COUNTER
    RUN_GAME_COUNTER += 1
    # 对局编号：跨进程也基本不重复，用于离线按局归集样本
    game_id = "%s-%d" % (RUN_TIME_TAG, RUN_GAME_COUNTER)

    # 强制随机数种子
    # random_seed = 1

    # 初始化神经网络样本集，用于打印
    NN_Sample_Data = []

    print("\n=================== Init Game =========================")

    # 创建游戏
    game = Game(PLAYERS, HANDCARDS)

    # 创建所有玩家对象
    playerList = []
    for i in range(1, PLAYERS+1):
        exec("P%d = Player('P%d')" %(i, i))  # 需要创建新变量时，用 exec，否则可以用 exec 或 eval
        eval("playerList.append(P%d)" %i)
    
    # 赋予玩家不同身份
    # model_path 可以是单个路径（所有人都用它），也可以是按座位排的列表
    #   —— 后者用于「新一代 vs 上一代」的对照评测
    if isinstance(model_path, (list, tuple)):
        model_paths = list(model_path)
        if len(model_paths) < PLAYERS:
            raise ValueError("model_path 列表长度(%d) < 玩家人数(%d)" % (len(model_paths), PLAYERS))
    else:
        model_paths = [model_path] * PLAYERS
    for i, player_type in enumerate(player_types):
        playerList[i].intellegence = player_type
        # 神经网络玩家需要加载模型
        if player_type == "network":
            playerList[i].NN_model = load_model(model_paths[i])
        # 策略网络玩家（第四轮）
        elif player_type == "policy":
            playerList[i].NN_model = load_policy(model_paths[i])
        # 打分式策略玩家（第五轮）：架构与 Q 网络相同，用同一个加载函数
        # 混合型玩家（第十一轮）也用打分网络做剪枝
        elif player_type in ("scorepolicy", "hybrid"):
            playerList[i].NN_model = load_model(model_paths[i])
        # 树集成对照实验：GBDT（见 gbdt.py，懒加载避免 torch 环境也要 numpy）
        elif player_type == "gbm":
            from gbdt import load_model as load_gbdt_model
            playerList[i].NN_model = load_gbdt_model(model_paths[i])

    # 每个座位的额外设置（比如 search_depth 不同，用于 L1 的对照实验）
    if player_opts:
        for i in range(min(len(player_opts), PLAYERS)):
            for k, v in (player_opts[i] or {}).items():
                setattr(playerList[i], k, v)

    # 创建牌堆
    # cardDeck = CardDeck()  # 默认情况，104张牌都发出
    cardDeck = CardDeck(players=PLAYERS)  # 只发出和玩家数量对应的牌
    
    # 显示所有牌的信息
    # for card in cardDeck:
    #     card.showInfo()

    # 设置牌局随机数种子
    if random_seed != -1:
        random.seed(random_seed)

    # 洗牌
    random.shuffle(cardDeck)

    # 发牌
    for p in playerList:
        for i in range(game.max_round):
            p.handCards.append(cardDeck.pop(0))
        # 人类玩家的手牌将被排序
        if p.intellegence == "human":
            p.sortHandCards()
        p.showHandCards()

    # 翻4张底牌
    for i in range(4):
        game.table[i][0] = cardDeck.pop(0)
    # 开局这 4 张也算「已出牌」
    game.played_cards = [game.table[i][0].value for i in range(4)]
    game.played_bullheads = sum(game.table[i][0].bullheads for i in range(4))
    # 记录这副牌的总牛头数（用于推算对手手牌）与玩家列表（用于读取对手分数）
    game.deck_total_bullheads = sum(card.bullheads for card in cardDeck.shadow)
    game.playerList = playerList
    game.showTable()

    # 显示剩余牌堆
    cardDeck.showCards()

    # 游戏开始
    for i in range(game.max_round):
        print("\n=============== Start Round %s ===================" % str(i+1))

        # 显示当前桌面牌型，并存入样本集：前40位
        game.table_data = game.showTable()

        # 本回合开始前各玩家的累计牛头，用于计算真实罚分和 reward-to-go
        score_before = {p.name: p.bullheads for p in playerList}

        # 玩家出牌，并将桌面牌型和手牌加入样本集
        for p in playerList:
            p.played_smallest = False  # 重置玩家状态
            p.playCard(game, cardDeck)

        # 处理缓存区：比较玩家出牌大小，并按顺序放置牌
        game.arrangeCard()
        game.stash = []  # 清空缓存区
        
        for p in playerList:
            p.showPenaltyCards()
            # 本回合真实罚分（不是 advAi 的估计值）
            penalty = p.bullheads - score_before[p.name]
            # NN_data_0 = 出牌决策，NN_data_1 = 打出最小牌后选行的决策
            # 两者都发生在结算之前，所以共享同一个 reward-to-go
            for data, is_used in ((p.NN_data_0, p.NN_data_0.action[0] != -1),
                                  (p.NN_data_1, p.NN_data_1.action[0] != -1 and p.played_smallest)):
                # 神经网络玩家的动作不加入样本；评测时不写样本
                if not (is_used and record_to_file):
                    continue
                data.game_id = game_id
                data.round = i + 1
                data.seat = int(p.name.replace("P", ""))
                data.penalty_this_round = penalty
                data.score_before_round = score_before[p.name]
                data.calcFinalList()
                # 将当前回合的样本加入总样本集，最后统一打印
                # （去掉 game_id 字符串自带的引号，让 CSV 干净些）
                sample_data = str(data.final_list).strip("[").strip("]").replace("'", "")
                NN_Sample_Data.append(sample_data + "\n")

        # 游戏剩余回合数-1
        game.leftRoundDecrement()

    # 游戏结束，显示桌面和分数
    print("\n=================== Game End =======================")
    game.showTable()
    for p in playerList:
        p.showPenaltyCards()
        
    # 额外打印游戏结果summary
    game_result_filename = "game_log/game_result.txt"
    if random_seed != -1:
        game_result_filename = "game_log/autoplay/game_result_%d.txt" % random_seed
    bullhead_list = []
    bullhead_list_noised = []
    with (open(game_result_filename, "w") if (record_to_file and PER_GAME_FILES) else NullFile()) as f:
        for i in range(PLAYERS):
            bullhead_list.append(playerList[i].bullheads)
            # 根据随机数种子，给牛头数增加小于1的修正值，确保有有多个玩家牛头最少时，winner能够随机分布
            noise = 0.1 * ((random_seed % PLAYERS + i) % PLAYERS)
            bullhead_noised = playerList[i].bullheads + noise
            bullhead_list_noised.append(bullhead_noised)
            f.write("P%d's Bullheads: %d\n" % (i+1, bullhead_list[i]))
        winner = bullhead_list_noised.index(min(bullhead_list_noised))
        f.write("P%s wins." % str(winner + 1))
        # 打印修正后的牛头数值，供debug
        f.write("\n\n# bullheads with noise:\n%s" % str(bullhead_list_noised))
        f.close()
    
    if statistic and record_to_file:
        # 在已有的文件后面添加行
        with open("game_log/00_statistics.csv", "a") as f:
            f.write("%d," % random_seed)
            for p in playerList:
                f.write(str(p.bullheads) + ',')
            f.write("P%s\n" % str(winner + 1))
    
    # 生成神经网络训练样本集
    # 每局游戏
    nn_sample_data_filename = "game_log/nn_sample_data.csv"
    if random_seed != -1:
        nn_sample_data_filename = "game_log/autoplay/nn_sample_data_%d.csv" % random_seed
    
    # 将记录打乱后再保存
    random.shuffle(NN_Sample_Data)

    # csv_headers = "Table11,,,,,,,,,,Table21,,,,,,,,,,Table31,,,,,,,,,,Table41,,,,,,,,,,\
    #     HandCard0,,,,,,,,,,,,,,,,,,HandCard9,,leftHandCard,CurrBullheads,Situation,Action,Reward"
    csv_headers = "HandCard0,,,,,,,,,,,,,,,,,,HandCard9,,BlanksRow1,,,BlanksRow4,LastCardRow1,,,,,,LastCardRow4,,\
        BullheadsRow1,,,BullheadsRow4,Players,leftHandCard,CurrBullheads,Situation,Action0,,,,,,,,,Action9,ChooseRow1,,,ChooseRow4,Reward,\
        GameId,Round,Seat,PenaltyThisRound,ScoreBeforeRound"
    # 额外特征的列名，保证表头列数与数据一致
    if extra_feature_mode == "row_segments":
        csv_headers = csv_headers.replace(",Action0", ",SegRow1,SegRow2,SegRow3,SegRow4,Action0")
    elif extra_feature_mode == "played_onehot":
        csv_headers = csv_headers.replace(",Action0", "," + ",".join("Played%d" % v for v in range(1, 25)) + ",Action0")
    elif extra_feature_mode == "hand_bullheads":
        csv_headers = csv_headers.replace(",Action0", ",OppScore,MyHandBullheads,OppHandBullheads,Action0")
    elif extra_feature_mode == "teacher_scores":
        csv_headers = csv_headers.replace(",Action0", "," + ",".join("TeacherScore%d" % i for i in range(14)) + ",Action0")
    elif extra_feature_mode == "teacher_summary":
        csv_headers = csv_headers.replace(",Action0", ",TMin,TMean,TMargin,TSafeCount,TMax,Action0")
    if record_to_file:
        # 每局一份的样本文件（策略采样、评测时不需要，只保留总表）
        if PER_GAME_FILES:
            with open(nn_sample_data_filename, "w") as f:
                f.write(csv_headers + "\n")
                f.writelines(NN_Sample_Data)
                f.close()
        # 历史总表
        with open(SAMPLE_DATA_MASTER, "a") as f:
            f.writelines(NN_Sample_Data)
            f.close()

    return {"bullheads": bullhead_list, "winner": winner}

if __name__ == "__main__":

    # 用法: python game_6nimmt.py [players] [random_seed] [statistic] [player_types] [model_path] [extra_feature_mode] [normalize]
    # 例如: python game_6nimmt.py 2 -1 nostat "simple_ai,network" model_30.pth
    #       python game_6nimmt.py 2 -1 nostat "scorepolicy,advanced_ai" model_score_T05.pth row_segments 0

    # 默认值
    players = 2
    random_seed = -1
    statistic = False
    player_types = None
    model_path = None
    
    # 如果有参数输入
    if len(sys.argv) > 3:
        players = int(sys.argv[1])
        random_seed = int(sys.argv[2])
        statistic = sys.argv[3] == "statistic"
    if len(sys.argv) > 4:
        player_types = [t.strip() for t in sys.argv[4].split(",")]
    if len(sys.argv) > 5:
        model_path = sys.argv[5]
    # 模型的特征配置必须和训练时一致，否则输入维度对不上
    if len(sys.argv) > 6:
        extra_feature_mode = sys.argv[6]
    if len(sys.argv) > 7:
        normalize_state = sys.argv[7].lower() not in ("0", "false")

    run_game(players, random_seed, statistic, player_types, model_path)
