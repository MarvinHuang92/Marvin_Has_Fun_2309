# 写两份列表，用于随机给人物命名，每个列表都分别使用26个首字母

name_list_raw = """
A: Alice, Adam 
B: Bob, Betty 
C: Charlie, Cathy 
D: David, Daisy 
E: Edwin, Eleanor 
F: Frank, Fiona 
G: George, Gina 
H: Henry, Hope 
I: Isaac, India 
J: Jack, Joyce 
K: Kevin, Kate 
L: Larry, Lisa 
M: Martin, Mary 
N: Neil, Nancy 
O: Oliver, Olive 
P: Peter, Patricia 
Q: Quincy, Queen 
R: Ralph, Rose 
S: Simon, Sarah 
T: Thomas, Terry 
U: Ursula, Unity 
V: Victor, Vera 
W: William, Wendy 
X: Xander, Xenia
Y: Yolanda, York
Z: Zoe, Zsa
"""

def generate_name_list():
    name_list_1 = []
    name_list_2 = []
    for line in name_list_raw.split("\n"):
        if not line == "":
            line = line.strip().split(":")[1]
            name_list_1.append(line.split(",")[0].strip())
            name_list_2.append(line.split(",")[1].strip())

    return name_list_1, name_list_2

# generate_name_list()
# print(name_list_1)
# print(name_list_2)