# coding=utf-8
import time
import os

import torch
from tqdm import tqdm
from torch.utils.data import Dataset, DataLoader
from torchvision.models import resnet34
import torch.nn as nn
import torch.optim as optim
from visdom import Visdom
import numpy as np
from torchvision.models import resnet152, vgg16, vgg16_bn, vgg19_bn, resnet50, resnext101_32x8d, densenet121, densenet201

from read_datas import ReaderDatas, ReaderClassfiedData, ReaderClassfiedCoatData
from utils import Evaluate
from utils import Flatten
from custom_models.custom_resnets import Resnet34, VGG19_bn, Resnet152, Densenet121, VGG16, Resnet18, VGG13


batchsz = 3
lr = 1e-4
epochs = 500
# device = torch.device('cuda')
torch.manual_seed(1234)
class_sample_counts = [900, 150, 40, 8, 4]


use_gpu = torch.cuda.is_available()
if use_gpu:
    device = torch.device('cuda')

viz = Visdom()
viz.line([[0., 0.]], [0], win='train', opts=dict(title='loss&f1', legend=['loss', 'f1']))


def data_load(file_root=os.path.join('datas', 'data3', 'category')):
    # train_db = ReaderDatas(picture_root='.\\datas\\data2\\noval-seg-last', resize=244, mode="train",
    #                        task_label="苔色", category=['白', '淡黄', '黄', '焦黄', '灰黑'],
    #                        label_filename='.\\datas\\data2\\st2_total_detail(20220506)_sm_noval_last.json')
    # val_db = ReaderDatas(picture_root='.\\datas\\data2\\noval-seg-last', resize=244, mode="val",
    #                      task_label="苔色", category=['白', '淡黄', '黄', '焦黄', '灰黑'],
    #                      label_filename='.\\datas\\data2\\st2_total_detail(20220506)_sm_noval_last.json')
    # test_db = ReaderDatas(picture_root='.\\datas\\data2\\noval-seg-last', resize=244, mode="test",
    #                       task_label="苔色", category=['白', '淡黄', '黄', '焦黄', '灰黑'],
    #                       label_filename='.\\datas\\data2\\st2_total_detail(20220506)_sm_noval_last.json')
    train_db = ReaderClassfiedData(root=file_root, mode='train')
    val_db = ReaderClassfiedData(root=file_root, mode='test')
    test_db = ReaderClassfiedData(root=file_root, mode='test')
    # 重采样
    weights = 1. / torch.tensor(class_sample_counts, dtype=torch.float)
    train_targets = train_db.labels
    samples_weights = weights[train_targets]
    sampler = torch.utils.data.WeightedRandomSampler(weights=samples_weights,
                                                     num_samples=len(samples_weights), replacement=True)

    train_loader = DataLoader(train_db, batch_size=batchsz, shuffle=False, sampler=sampler)  # num_workers=2
    val_loader = DataLoader(val_db, batch_size=batchsz)
    test_loader = DataLoader(test_db, batch_size=batchsz)

    return train_loader, val_loader, test_loader


class SelfDefineModel(nn.Module):

    def __init__(self):
        super(SelfDefineModel, self).__init__()
        self.trained_model = resnet152(pretrained=True)  # .to(device)
        self.model1 = nn.Sequential(*list(self.trained_model.children())[:-1],  # 测试一下输出维度[b, 512, 1, 1]
                                    Flatten(),
                                    nn.Linear(2048, 512),
                                    nn.Dropout(p=0.3),
                                    nn.ReLU(inplace=True),
                                    nn.Linear(512, 10),
                                    )
        self.trained_model2 = vgg16(pretrained=True)  # .to(device)
        self.model2 = nn.Sequential(*list(self.trained_model2.children())[:-1],  # 测试一下输出维度[b, 512, 1, 1]
                                    Flatten(),
                                    nn.Linear(25088, 5000),
                                    nn.Dropout(p=0.3),
                                    nn.ReLU(),
                                    nn.Linear(5000, 200),
                                    nn.Dropout(p=0.2),
                                    nn.ReLU(),
                                    nn.Linear(200, 10)
                                    )
        self.model3 = nn.Sequential(
            nn.Dropout(p=0.1),
            nn.ReLU(),
            nn.Linear(20, 5)
        )
        # self.trained_model4 = vgg16(pretrained=True)  # .to(device)
        # self.model4 = nn.Sequential(*list(self.trained_model4.children())[:-1],  # 测试一下输出维度[b, 512, 1, 1]
        #                             Flatten(),
        #                             nn.Linear(25088, 5000),
        #                             nn.ReLU(),
        #                             nn.Linear(5000, 200),
        #                             nn.ReLU(),
        #                             nn.Linear(200, 5)
        #                             )

    def forward(self, x):
        x1 = self.model1(x)
        x2 = self.model2(x)
        # x4 = self.model4(x)
        x = torch.cat([x1, x2], dim=1)
        x = self.model3(x)
        return x


def main():

    train_loader, val_loader, test_loader = data_load()

    model = SelfDefineModel()
    # model.load_state_dict(torch.load('best.mdl'))
    lr = 1e-5
    optimizer = optim.Adam(model.parameters(), lr=lr)
    criteon = nn.CrossEntropyLoss()

    use_gpu = torch.cuda.is_available()
    if use_gpu:
        model = model.to(device)
        criteon = criteon.to(device)

    best_f1 = 0
    best_epoch = 0
    for epoch in tqdm(range(epochs)):
        model.train()
        train_loader, val_loader, _ = data_load()
        for step, (x, y, img_name) in enumerate(train_loader):
            if use_gpu:
                x, y = x.to(device), y.to(device)
            logit = model(x)
            loss = criteon(logit, y)
            coe = torch.tensor(6e-6)
            l2_reg = torch.tensor(0.)
            if use_gpu:
                coe = coe.to(device)
                l2_reg = l2_reg.to(device)
            # for param in model.parameters():
            #     l2_reg += torch.norm(param)
            #     loss += coe * l2_reg

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        result = Evaluate(model, test_loader)
        f1 = result.return_f1()
        if f1 < 0.35:
            lr = 1e-4
            optimizer = optim.Adam(model.parameters(), lr=lr)
        if f1 > 0.35:
            lr = 7e-5
            optimizer = optim.Adam(model.parameters(), lr=lr)
        if f1 > 0.4:
            lr = 4e-5
            optimizer = optim.Adam(model.parameters(), lr=lr)
        if f1 > 0.45:
            lr = 4e-5
            optimizer = optim.Adam(model.parameters(), lr=lr)
        if epoch % 1 == 0:
            model.eval()
            result = Evaluate(model, test_loader)
            result.print_error_case()
            result2 = Evaluate(model, train_loader)
            f1 = result.return_f1()
            if f1 > best_f1:
                best_epoch = epoch
                best_f1 = f1
                # 保存参数
                torch.save(model.state_dict(), 'best.mdl')
                result.save_classification_report()
            print('epoch:', epoch)
            print('loss：', loss)
            result.print_classification_report()
            result2.print_classification_report()
            # 可视化
            loss_ = loss
            loss_ = loss_.detach().cpu()
            viz.line([[loss_, f1]], [epoch], win='train', update='append')
            time.sleep(0.5)

    # 加载参数
    model.load_state_dict(torch.load('best.mdl'))
    test_acc = Evaluate(model, test_loader).return_acc()
    print(test_acc)
    Evaluate(model, test_loader).print_classification_report()


def test_data2():
    train_db = ReaderDatas(picture_root='.\\datas\\data2\\noval-seg-last', resize=244, mode="train",
                           task_label="苔色", category=['白', '淡黄', '黄', '焦黄', '灰黑'], label_filename='.\\datas\\data2\\st2_total_detail(20220506)_sm_noval_last.json')
    test_db = ReaderDatas(picture_root='.\\datas\\data2\\noval-seg-last', resize=244, mode="test",
                          task_label="苔色", category=['白', '淡黄', '黄', '焦黄', '灰黑'],
                          label_filename='.\\datas\\data2\\st2_total_detail(20220506)_sm_noval_last.json')
    new_data = train_db+test_db
    # old_data = ReaderDatas(mode='test', category=['白', '淡黄',  '黄', '焦黄', '灰黑'])
    train_loader = DataLoader(new_data, batch_size=batchsz)
    model = SelfDefineModel()
    model.load_state_dict(torch.load('best.mdl'))
    test_acc = Evaluate(model, train_loader).return_acc()
    print(test_acc)
    Evaluate(model, train_loader).print_classification_report()
# Press the green button in the gutter to run the script.


if __name__ == '__main__':
    test_data2()
