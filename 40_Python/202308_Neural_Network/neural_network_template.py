from torch import nn, float32
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # 用于绘制三维图像


# 基本步骤：
# 1. 定义神经网络类 Network (包含中间层种类：线性 or 卷积，激活函数的选择)
# 2. 创建神经网络实例
# 3. 定义 loss 损失函数（取决于问题类型：线性、非线性），和优化器
# 4. 开始迭代，训练模型（找到使得 loss 最小的权重参数）


# 定义神经网络类（激活函数，隐藏层数量不变时，可以直接复用）
class Network(nn.Module):
    # 重载初始化函数（构造函数）
    # 传入参数：输入层，隐藏层，输出层
    def __init__(self, n_in, n_hidden, n_out, activation_func):
        super().__init__()  # 首先调用父类的初始化函数
        # 使用传入的激活函数类型 - 解决不同问题，使用的激活函数也不同
        self.activation_func = activation_func
        # 然后新增步骤，创建两个线性层
        self.layer1 = nn.Linear(n_in, n_hidden)
        self.layer2 = nn.Linear(n_hidden, n_out)

    # 定义前向传播
    def forward(self, x):
        x = self.layer1(x)  # 计算 layer1 结果
        x = self.activation_func(x)  # 调用激活函数
        return self.layer2(x)  # 返回 layer2 结果


class Network_2_hidden_layer(nn.Module):
    # 重载初始化函数（构造函数）
    # 传入参数：输入层，隐藏层，输出层
    def __init__(self, n_in, n_hidden_1, n_hidden_2, n_out, activation_func):
        super().__init__()  # 首先调用父类的初始化函数
        # 使用传入的激活函数类型 - 解决不同问题，使用的激活函数也不同
        self.activation_func = activation_func
        # 然后新增步骤，创建3个线性层
        self.layer1 = nn.Linear(n_in, n_hidden_1)
        self.layer2 = nn.Linear(n_hidden_1, n_hidden_2)
        self.layer3 = nn.Linear(n_hidden_2, n_out)

    # 定义前向传播
    def forward(self, x):
        x = self.layer1(x)  # 计算 layer1 结果
        x = self.activation_func(x)  # 调用激活函数
        x = self.layer2(x)  # 计算 layer2 结果
        x = self.activation_func(x)  # 调用激活函数
        return self.layer3(x)  # 返回 layer3 结果


class Network_3_hidden_layer(nn.Module):
    # 重载初始化函数（构造函数）
    # 传入参数：输入层，隐藏层，输出层
    def __init__(self, n_in, n_hidden_1, n_hidden_2, n_hidden_3, n_out, activation_func):
        super().__init__()  # 首先调用父类的初始化函数
        # 使用传入的激活函数类型 - 解决不同问题，使用的激活函数也不同
        self.activation_func = activation_func
        # 然后新增步骤，创建4个线性层
        self.layer1 = nn.Linear(n_in, n_hidden_1)
        self.layer2 = nn.Linear(n_hidden_1, n_hidden_2)
        self.layer3 = nn.Linear(n_hidden_2, n_hidden_3)
        self.layer4 = nn.Linear(n_hidden_3, n_out)

    # 定义前向传播
    def forward(self, x):
        x = self.layer1(x)  # 计算 layer1 结果
        x = self.activation_func(x)  # 调用激活函数
        x = self.layer2(x)  # 计算 layer2 结果
        x = self.activation_func(x)  # 调用激活函数
        x = self.layer3(x)  # 计算 layer3 结果
        x = self.activation_func(x)  # 调用激活函数
        return self.layer4(x)  # 返回 layer4 结果


# 对于图形输入，上述模板类不好用，会报错 mat1 mat2 shape不符合
class Network_2_hidden_layer_for_image(nn.Module):
    # 重载初始化函数（构造函数）
    # 传入参数：输入层，隐藏层，输出层
    def __init__(self, n_in, n_hidden_1, n_hidden_2, n_out):
        super().__init__()  # 首先调用父类的初始化函数
        self.flatten = nn.Flatten()
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(n_in, n_hidden_1),
            nn.ReLU(),
            nn.Linear(n_hidden_1, n_hidden_2),
            nn.ReLU(),
            nn.Linear(n_hidden_2, n_out),
        )

    # 定义前向传播
    def forward(self, x):
        x = self.flatten(x)
        return self.linear_relu_stack(x)  # 返回 layer3 结果

# 卷积神经网络，3个卷积层
class Convolve_Network_3_kernel(nn.Module):
    # 重载初始化函数（构造函数）
    # 传入参数：输入层，隐藏层，输出层
    def __init__(self, in_channels, conv_channels, out_channels, kernal_sizes, image_size, conv_layers=3):
        super().__init__()  # 首先调用父类的初始化函数
        self.flatten = nn.Flatten()

        # 转换格式，支持整型或list输入
        if type(conv_channels) == type(int()):
            conv_channels = [conv_channels]*(conv_layers)
        if type(kernal_sizes) == type(int()):
            kernal_sizes = [kernal_sizes]*conv_layers
        if type(image_size) == type(int()):
            image_size = [image_size]*2
        
        # 定义卷积层（特征提取）
        # in_channels: 输入颜色通道数（根据图像类型选1或3）
        # out_channels: 输出的特征种类数（可以自定义）
        # conv_layers: 卷积层数量
        self.convs_stack = nn.Sequential(
            nn.Conv2d(in_channels, conv_channels[0], kernal_sizes[0]),
            nn.ReLU(),
            nn.Conv2d(conv_channels[0], conv_channels[1], kernal_sizes[1]),
            nn.ReLU(),
            nn.Conv2d(conv_channels[1], conv_channels[2], kernal_sizes[2]),
        )

        # 定义池化层
        self.polling_layer = nn.MaxPool2d(kernel_size=2, stride=2, padding=0)

        # 计算全连接层输入维度
        def calcLinearInDim(input_dim, kernel_dim, stride=1, padding=0):
            # 每次计算一个边长，长度或宽度
            return (input_dim - kernel_dim + 2*padding)//stride + 1

        # 计算卷积层对维度的影响
        dim_w, dim_h = image_size
        for k_s in kernal_sizes:
            dim_w = calcLinearInDim(dim_w, k_s)
            dim_h = calcLinearInDim(dim_h, k_s)
        # 计算池化层对维度的影响
        dim_w = calcLinearInDim(dim_w, kernel_dim=2, stride=2)
        dim_h = calcLinearInDim(dim_h, kernel_dim=2, stride=2)
        linear_in_features = conv_channels[-1] * dim_w * dim_h

        # 定义全连接层（分类器）
        # 这一步没有激活函数
        self.logits_layer = nn.Linear(in_features=linear_in_features, out_features=out_channels)

    # 定义前向传播
    def forward(self, x):
        x = self.convs_stack(x)    # 卷积运算
        x = self.polling_layer(x)  # 池化运算
        x = self.flatten(x)        # 数据维度重排，将 c*w*h 三个维度乘积作为一个维度，用于全连接层的输入
        x = self.logits_layer(x)   # 全连接分类
        return x


# 训练模型 - softmax 回归模型的循环迭代
def softmax_epoch(x, y, network, criterion, optimizer, n_epochs, n_print_loss):
    for epoch in range(n_epochs):
        y_pred = network(x)  # 调用forward 方法，预测输出

        # 计算预测值 y_pred 与真实值 y 之间的损失 loss
        loss = criterion(y_pred, y)
        loss.backward()  # 通过自动微分计算损失函数关于模型参数的梯度
        optimizer.step()  # 更新模型参数，使得损失函数减小
        optimizer.zero_grad()  # 将梯度清零，用于下一次迭代

        # 计算准确率 accuracy
        # 注意 y 的形状：分类任务是一维 (N,)，拟合任务是二维 (N,1)；不展平会广播成 N×N 的巨矩阵
        accuracy = (y_pred.argmax(1) == y.view(-1)).type(float32).sum().item() / len(y)

        # 模型的每一次迭代，都由前向传播，和反向传播组成
        if epoch % n_print_loss == 0:
            # 每迭代 n_print_loss 次，打印当前损失
            print("%d iterations: loss = %.4lf, accuracy = %.4lf" % (epoch, loss.item(), accuracy))
    
    return network



# 计算均方误差（参考值为0，而非样本的平均值）
def calcMSE(array):
    square_error = 0.0
    for a in array:
        square_error += a**2
    return square_error / len(array)


# 用于绘制二元函数 z = f(x, y)
def plot_3d_figure(X, Y, Z, x_label="x", y_label="y", z_label="z", title=""):
    fig = plt.figure()
    ax = plt.axes(projection='3d')  # 设置为3维
    ax.plot_surface(X, Y, Z, cmap='viridis')
    ax.set_xlabel(x_label)  # 设置坐标轴标签
    ax.set_ylabel(y_label)
    ax.set_zlabel(z_label)
    plt.title(title)  # 在图中显示函数表达式
    plt.show()


# 绘制二元函数图像的示例
"""
def f(x, y):  # 设置函数表达式
    return np.sin(x) + np.sin(y) - np.sin(x+y)

def draw_fxy_figure():
    x = np.linspace(-2*np.pi, 2*np.pi, 100)  # 设置变量范围, 100为样本点数
    y = np.linspace(-2*np.pi, 2*np.pi, 100)
    X, Y = np.meshgrid(x, y)
    Z = f(X, Y)
    plot_3d_figure(X, Y, Z, title="f(x,y)=sinx+siny-sin(x+y)")

draw_fxy_figure()
"""