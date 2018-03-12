import math
import torch
import torch.nn as nn


# the intuition is this:
# it does not modify the structure of the network, instead,
# it tries to add a few operations without modifying the
# network itself
class PoseNet(torch.nn.Module):

    def __init__(self, original_model):
        super(PoseNet, self).__init__()

        self.features = nn.Sequential(*list(original_model.children())[:-1])
        self.regressor = nn.Sequential(
            nn.Linear(512, 2048),
            nn.ReLU(inplace=True),
            nn.Dropout()
        )
        self.trans_regressor = nn.Sequential(
            nn.Linear(2048, 3)
        )
        self.rotation_regressor = nn.Sequential(
            nn.Linear(2048, 4)
        )
        self.modelName = 'resnet'

        # freeze those weights
        # for p in self.features.parameters():
        #     p.requires_grad = False

        for m in self.regressor.modules():
            if isinstance(m, nn.Linear):
                n = m.weight.size(0)
                m.weight.data.normal_(0, 0.01)
                m.bias.data.zero_()

        for m in self.trans_regressor.modules():
            if isinstance(m, nn.Linear):
                n = m.weight.size(0)
                m.weight.data[0].normal_(0, 0.5)  # ?
                m.weight.data[1].normal_(0, 0.5)
                m.weight.data[2].normal_(0, 0.1)
                m.bias.data.zero_()

        for m in self.rotation_regressor.modules():
            if isinstance(m, nn.Linear):
                n = m.weight.size(0)
                m.weight.data.normal_(0, 0.01)
                m.bias.data.zero_()

    def forward(self, input):
        f = self.features(input)
        f = f.view(f.size(0), -1)
        y = self.regressor(f)
        trans = self.trans_regressor(y)
        rotation = self.rotation_regressor(y)

        return trans, rotation
