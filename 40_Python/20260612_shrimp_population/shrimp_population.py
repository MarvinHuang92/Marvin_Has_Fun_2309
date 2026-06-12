# 模拟小虾的繁殖过程，时间单位为月
# 每个月，每只性成熟的雌虾会产下30只小虾，小虾需要3个月才能性成熟，考虑到抱卵期，第4个月结束时会产下小虾
# 新生的小虾有一半是雄虾，一半是雌虾
# 每只虾的寿命为18个月，第19个月时会死亡
# 初始时有1只性成熟的雌虾，计算经过24个月后，池塘里总共有多少只小虾

# 参数
LIFESPAN = 18  # 虾的寿命为18个月
MATURITY_AGE = 4  # 性成熟的年龄为4个月
OFFSPRING_PER_FEMALE = 30  # 每只性成熟的雌虾每个月产下的小虾数量
SIMULATION_MONTHS = 12  # 模拟时长（24个月会导致电脑直接卡死，先用12个月代替）

class Shrimp:
    def __init__(self, age=0, is_female=True):
        self.age = age
        self.is_female = is_female

class Pond:
    def __init__(self):
        self.shrimps = [Shrimp(age=MATURITY_AGE, is_female=True)]  # 初始时有1只性成熟的雌虾(年龄为4个月)
        self.month = 0
        self.population_history = []
        self.birth_history = []
        self.death_history = []
        self.male_history = []
        self.female_history = []
        self.death_number = 0
        self.update_population_history()

    def update_population_history(self):
        self.population_history.append(len(self.shrimps))
        self.birth_history.append(sum(1 for shrimp in self.shrimps if shrimp.age == 0))
        self.death_history.append(self.death_number)  # 死亡个体已经移除出self.shrimps，无法通过sum统计，所以直接记录死亡数量
        self.male_history.append(sum(1 for shrimp in self.shrimps if not shrimp.is_female))
        self.female_history.append(sum(1 for shrimp in self.shrimps if shrimp.is_female))

    def simulate_shrimp_population(self, end_month):
        while self.month < end_month:
            self.month += 1
            self.death_number = 0  # 重置本月的死亡数量
            new_shrimps = []
            survivors = []
            for shrimp in self.shrimps:
                shrimp.age += 1
                if shrimp.age <= LIFESPAN:  # 虾的寿命为18个月
                    survivors.append(shrimp)
                    if shrimp.is_female and shrimp.age >= MATURITY_AGE:  # 性成熟的雌虾每个月产下30只小虾
                        for _ in range(OFFSPRING_PER_FEMALE // 2):  # 产下的小虾一半是雄虾，一半是雌虾
                            new_shrimps.append(Shrimp(age=0, is_female=True))
                            new_shrimps.append(Shrimp(age=0, is_female=False))
                else:
                    self.death_number += 1
            self.shrimps = survivors  # 先收集幸存者，再一次性替换，避免遍历时删除导致漏算
            self.shrimps.extend(new_shrimps)  # 将新生的小虾加入总人口
            self.update_population_history()
        return len(self.shrimps)

if __name__ == "__main__":
    pond = Pond()
    pond.simulate_shrimp_population(SIMULATION_MONTHS)
    print(f"每个月的虾的数量历史记录: {pond.population_history}")
    print(f"每个月的新生虾数量历史记录: {pond.birth_history}")
    print(f"每个月的死亡虾数量历史记录: {pond.death_history}")
    print(f"每个月的雄虾数量历史记录: {pond.male_history}")
    print(f"每个月的雌虾数量历史记录: {pond.female_history}")