# 6 Nimmt!（牛头牌 / Take 5）神经网络 AI

用 PyTorch 训练神经网络去玩桌游 **6 Nimmt!** 的练习项目（2023-10-22 起）。

一句话：**游戏引擎自己写 → 对局中把 (局面, 动作, 得分) 录成样本 → 训练「局面+动作 → 预期罚分」的回归网络 →
打牌时枚举合法动作取预测最小**。本质是**监督学习模仿一个手写启发式**，不是强化学习。
后来又往前走了三步：**拿搜索当老师**（蒸馏）、**让网络只负责剪枝、搜索负责决策**（hybrid）、
以及**多人局重训**。

## 当前状态（2026-11-23 整理）

| 项目 | 结论 |
|---|---|
| **最强配置** | `hybrid`（网络剪枝 + 前 3 名各 24 次 rollout） |
| **2 人局强度** | vs 随机对手 **94~95.5%** 胜率（起点 66.7%） |
| **理论上限提醒** | 这个口径下已接近天花板；再往上要换对手（人类 / 自对弈）或换算法族（真正的 MCTS） |
| **多人局** | 混合人数训练是唯一有效的改动（Lv2 从 11.68 → 9.54） |
| **已证伪的方向** | 自造特征、换标签（RTG / 优势）、残差结构、成对比较、归一化、KL 约束、加容量、加数据、加 rollout、偷看手牌、网络与 rollout 混合打分——**全部实测无效或有害** |

> 想直接看"哪些方法有用、哪些没用、为什么"——读 **[docs/AI迭代历程.md](docs/AI迭代历程.md)**。
> 想看每一轮的原始实验数据——读 [docs/优化记录.md](docs/优化记录.md)。

## 快速开始

```powershell
cd D:\Programming\Marvin_Has_Fun_2309\40_Python\20231022_6Nimmt

# 依赖：torch、matplotlib（numpy 是 torch 的依赖）
# 本机可用：D:\Programming\Python_dir_38\python.exe（torch 2.4.1+cpu / matplotlib 3.7.5）

# 图形界面：你 + 1~9 个电脑（对手类型逐个可选），只要标准库 tkinter
python gui_6nimmt.py

# 单局：神经网络 vs 普通电脑
python game_6nimmt.py 2 -1 nostat "network,simple_ai" model_30.pth

# 批量对战 + 胜率统计（1000 局）
python autoplay.py 1000 2 "network,simple_ai" model_30.pth

# 固定种子、可复现的评测（当前最强配置）
set HYBRID_TOP_K=3
set SEARCH_ROLLOUTS=24
python evaluate.py --games=4000 --model=models/model_searchc_25k400_ts.pth ^
                   --mode=teacher_scores --player=hybrid --seed=950000 --opponent=simple_ai

# 训练：任务类型和网络结构在 neural_network_run.py 里改
python neural_network_run.py
```

**必须在 `20231022_6Nimmt` 目录下运行**：所有 `game_log/...` 路径都是相对的，
且 `sys.path.append("../202308_Neural_Network")` 要靠当前目录找到模型类。

> ⚠️ `autoplay.py` 启动时会**删掉 `game_log\autoplay\` 下的旧日志**，并把新样本 append 到
> `game_log\02_nn_sample_data_full_v2.csv`。想保留旧数据先备份 `game_log`。
>
> `neural_network_run.py` 里 `plot = True` 会弹 `plt.show()`；只想看命令行输出可以设 `$env:MPLBACKEND="Agg"`。

完整的命令行参数、样本格式、网络结构说明见 **[docs/说明.md](docs/说明.md)**。

## 文档

| 文档 | 内容 |
|---|---|
| **[docs/AI迭代历程.md](docs/AI迭代历程.md)** | **⭐ 14 轮迭代的浓缩版**：成绩阶梯、有用/无用的完整清单、时间成本、可迁移的方法论，以及与拖拉机项目的对照 |
| [docs/说明.md](docs/说明.md) | 完整设计与使用说明（含命令行参数、样本结构、模型文件说明） |
| [docs/优化记录.md](docs/优化记录.md) | 第一~十四轮的逐轮实验记录（1638 行，最详细） |
| [docs/多人重训.md](docs/多人重训.md) | 多人局（5/6/7 人）重训全过程 |
| [docs/搜索调参.md](docs/搜索调参.md) | 搜索端八个消融（只有 rollout 次数 M 有拐点） |
| [docs/小状态版游戏.md](docs/小状态版游戏.md) | 把游戏缩到可穷举的规模，求"对随机对手的最优"（理论标尺） |
| [docs/真minimax.md](docs/真minimax.md) | 小状态版上的真 minimax 与博弈值分析 |
| [docs/L1价值头.md](docs/L1价值头.md) | 价值头的消融（rollout 截断深度） |
| [docs/lightgbm对照.md](docs/lightgbm对照.md) | 用 LightGBM 对照神经网络的必要性 |
| [docs/GPU可行性.md](docs/GPU可行性.md) | GPU 在这个规模下**更慢**的实测 |
| [docs/决策问题六根轴.md](docs/决策问题六根轴.md) | 方法论：决定算法选型的六根轴 + 六种游戏对照 |

## 目录结构

| 路径 | 用途 |
|---|---|
| `game_6nimmt.py` | 游戏引擎 + 各类玩家（最大单文件） |
| `gui_6nimmt.py` | Tkinter 图形界面 |
| `neural_network_6nimmt.py` / `train_policy.py` / `policy_6nimmt.py` | 网络定义与训练 |
| `evaluate.py` | 固定种子、可复现的评测（**结论都以它为准**） |
| `benchmark.py` / `autoplay.py` | 两两对战矩阵 / 批量对战 |
| `search_noise.py` / `advantage_label.py` / `reward_to_go.py` | 搜索噪声分析 / 优势标签 / 离线重算标签 |
| `small_game_solver.py` / `minimax_small_game.py` / `verify_small_game.py` | 小状态版的理论标尺 |
| `models/` | 训练好的模型（`.pth`） |
| `game_log/` | 对局与训练样本日志 |
| `docs/` | 全部文档 |

## 已知限制

- 评测口径是"打完全随机的对手"，95% 已接近这个设定的天花板；对**人类**或**另一个 hybrid** 的胜率没有系统测过。
- 多人局模型目前是"2 人局数据 + 混合人数补充"，不是端到端的多人训练。
- 依赖 torch（不是纯标准库）；GUI 是纯 tkinter。
