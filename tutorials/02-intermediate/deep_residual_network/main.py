import math
import os
import tarfile
import urllib.request

import mindspore.common.dtype as mstype
import mindspore.dataset.vision
import mindspore.dataset.vision.transforms as transforms
import mindspore.nn as nn
import mindspore.ops as ops
from mindspore import Tensor
from mindspore.common.initializer import HeUniform

file_path = '../../../data/CIFAR-10'

if not os.path.exists(file_path):
    if not os.path.exists('../../../data'):
        os.mkdir('../../../data')
    # 下载CIFAR-10数据集
    os.mkdir(file_path)
    url = 'https://www.cs.toronto.edu/~kriz/cifar-10-binary.tar.gz'
    file_name = 'cifar-10-binary.tar.gz'
    print("正在从" + url + "下载CIFAR-10数据集...")
    result = urllib.request.urlretrieve(url, os.path.join(file_path, file_name))
    with tarfile.open(os.path.join(file_path, file_name), 'r:gz') as tar:
        print("正在解压数据集...")
        for member in tar.getmembers():
            if member.name.startswith('cifar-10-batches-bin'):
                member.name = os.path.basename(member.name)
                tar.extract(member, path=file_path)
    os.remove(os.path.join(file_path, file_name))

# 超参数
num_epochs = 80
batch_size = 100
learning_rate = 0.001

# 预处理
data_transforms = [
    transforms.Pad(4),
    transforms.RandomHorizontalFlip(),
    transforms.RandomCrop(32),
    transforms.ToTensor()]

# 导入CIFAR-10数据集
train_dataset = mindspore.dataset.Cifar10Dataset(
    dataset_dir=file_path,
    usage='train',
    shuffle=True
).map(operations=data_transforms, input_columns="image").batch(batch_size=batch_size)

test_dataset = mindspore.dataset.Cifar10Dataset(
    dataset_dir=file_path,
    usage='test',
    shuffle=False
).map(operations=transforms.ToTensor()).batch(batch_size=batch_size)


# 3x3 convolution
def Conv3x3(in_channels, out_channels, stride=1):
    return nn.Conv2d(in_channels, out_channels, kernel_size=3,
                     stride=stride, padding=1, pad_mode='pad')


# Residual block
class ResidualBlock(nn.Cell):
    def __init__(self, in_channels, out_channels, stride=1, downsample=None):
        super(ResidualBlock, self).__init__()
        self.conv1 = Conv3x3(in_channels, out_channels, stride)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU()
        self.conv2 = Conv3x3(out_channels, out_channels)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.downsample = downsample

    def construct(self, x):
        residual = x
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)
        out = self.bn2(out)
        if self.downsample:
            residual = self.downsample(x)
        out += residual
        out = self.relu(out)
        return out


# ResNet
class ResNet(nn.Cell):
    def __init__(self, block, layers, num_classes=10):
        super(ResNet, self).__init__()
        self.in_channels = 16
        self.conv = Conv3x3(3, 16)
        self.bn = nn.BatchNorm2d(16)
        self.relu = nn.ReLU()
        self.layer1 = self.make_layer(block, 16, layers[0])
        self.layer2 = self.make_layer(block, 32, layers[1], 2)
        self.layer3 = self.make_layer(block, 64, layers[2], 2)
        self.avg_pool = nn.AvgPool2d(8)
        self.fc = nn.Dense(64, num_classes, weight_init=HeUniform(math.sqrt(5)))

    def make_layer(self, block, out_channels, blocks, stride=1):
        downsample = None
        if (stride != 1) or (self.in_channels != out_channels):
            downsample = nn.SequentialCell(
                Conv3x3(self.in_channels, out_channels, stride),
                nn.BatchNorm2d(out_channels))
        layers = []
        layers.append(block(self.in_channels, out_channels, stride, downsample))
        self.in_channels = out_channels
        for i in range(1, blocks):
            layers.append(block(out_channels, out_channels))
        return nn.SequentialCell(*layers)

    def construct(self, x):
        out = self.conv(x)
        out = self.bn(out)
        out = self.relu(out)
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = self.avg_pool(out)
        out = out.view(ops.shape(out)[0], -1)
        out = self.fc(out)
        return out


model = ResNet(ResidualBlock, [2, 2, 2])

# 定义损失函数和优化器
criterion = nn.CrossEntropyLoss()
optimizer = nn.optim.Adam(model.trainable_params(), learning_rate)
# 绑定损失函数
train_model = nn.WithLossCell(model, loss_fn=criterion)

train_model = nn.TrainOneStepCell(train_model, optimizer)

# 训练
curr_lr = learning_rate
for epoch in range(num_epochs):
    for i, (image, label) in enumerate(train_dataset.create_tuple_iterator()):
        total_step = train_dataset.get_dataset_size()
        train_model.set_train()
        label = mindspore.Tensor(label, mstype.int32)
        loss = train_model(image, label)

        if (i + 1) % 100 == 0:
            print('Epoch [{}/{}], Step [{}/{}], Loss: {:.4f}'
                  .format(epoch + 1, num_epochs, i + 1, total_step, loss.asnumpy().item()))

    # 调整学习率
    if (epoch + 1) % 20 == 0:
        curr_lr /= 3
        ops.assign(optimizer.learning_rate, Tensor(curr_lr))
        print("Current Leaning Rate:{}".format(optimizer.get_lr().asnumpy().item()))

# 测试模型
model.set_train(False)
correct = 0
total = 0
for image, label in test_dataset.create_tuple_iterator():
    label = mindspore.Tensor(label, mstype.int32)
    outputs = model(image)
    _, predicted = ops.max(outputs.value(), 1)
    total += label.shape[0]
    correct += (predicted == label).sum().asnumpy().item()

print('Test Accuracy of the model on the 10000 test images: {:.2f} %'.format(100 * correct / total))

# Save the model checkpoint
save_path = './resnet.ckpt'
mindspore.save_checkpoint(model, save_path)
