import shutil
import numpy as np
import math

import torch
import torch.nn as nn
import torch.backends.cudnn as cudnn
import torch.nn.parallel
import torch.optim
import torch.utils.data
import torchvision.models as models
import torchvision.transforms as transforms

import PoseData
from PoseNet import PoseNet


def main():
    best_loss = 10000  # starts with a very large loss
    start_epoch = 0
    # learning rate
    lr = 1e-4

    # use Resnet-34 for pretrained model of PoseNet
    original_model = models.resnet34(pretrained=True)

    # make PoseNet
    model = PoseNet(original_model)
    model.cuda(1)

    cudnn.benchmark = True

    # Data loading
    datadir = './KingsCollege'
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])

    train_loader = torch.utils.data.DataLoader(
        PoseData.PoseData(datadir, transforms.Compose([
            transforms.Scale(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            normalize
        ]), train=True),
        batch_size=75, shuffle=True,
        num_workers=8, pin_memory=True
    )

    val_loader = torch.utils.data.DataLoader(
        PoseData.PoseData(datadir, transforms.Compose([
            transforms.Scale(256),
            transforms.RandomCrop(224),
            transforms.ToTensor(),
            normalize
        ]), train=False),
        batch_size=75, shuffle=False,
        num_workers=8, pin_memory=True)

    # specify per-layer parameters
    optimizer = torch.optim.Adam([{'params': model.features.parameters(), 'lr': lr},
                                  {'params': model.regressor.parameters(), 'lr': lr},
                                  {'params': model.trans_regressor.parameters(), 'lr': lr},
                                  {'params': model.rotation_regressor.parameters(), 'lr': lr}],
                                 weight_decay=2e-4)

    for epoch in range(start_epoch, 160):
        adjust_learning_rate(optimizer, epoch)

        # tran for one epoch
        train(train_loader, model, optimizer, epoch)

        # evaluate on validation set
        loss, trans_loss, rotation_loss = validate(val_loader, model)

        # remember best loss and save checkpoint
        is_best = loss < best_loss
        best_loss = min(loss, best_loss)
        save_checkpoint({
            'epoch': epoch + 1,
            'state_dict': model.state_dict(),
            'best_loss': best_loss,
        }, is_best)


def train(train_loader, model, optimizer, epoch):
    losses = AverageMeter()
    trans_losses = AverageMeter()
    rotation_losses = AverageMeter()

    # switch to train mode
    model.train()
    beta = 500

    for i, (input, target) in enumerate(train_loader):
        target = target.cuda(1)
        input_var = torch.autograd.Variable(input.cuda(1))
        target_var = torch.autograd.Variable(target)

        # compute output
        trans_output, rotation_output = model(input_var)
        trans_loss = pose_loss(trans_output, target_var[:, 0:3])
        rotation_loss = pose_loss(rotation_output, target_var[:, 3:]) * beta
        loss = trans_loss + rotation_loss

        # measure and record loss
        losses.update(loss.data[0], input.size(0))
        trans_losses.update(trans_loss.data[0], input.size(0))
        rotation_losses.update(rotation_loss.data[0], input.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        print('Epoch: [{0}][{1}]\t'
              'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
              'Trans Loss {trans_loss.val:.4f} ({trans_loss.avg:.4f})\t'
              'Rotation Loss {rotation_loss.val:.4f} ({rotation_loss.avg:.4f})'.format(
            epoch, len(train_loader), loss=losses, trans_loss=trans_losses,
            rotation_loss=rotation_losses))


def validate(val_loader, model):
    losses = AverageMeter()
    trans_losses = AverageMeter()
    rotation_losses = AverageMeter()
    rotation_errors = AverageMeter()

    # switch to evaluate mode
    model.eval()
    beta = 500

    for i, (input, target) in enumerate(val_loader):
        target = target.cuda(1)
        input_var = torch.autograd.Variable(input.cuda(1), volatile=True)
        target_var = torch.autograd.Variable(target, volatile=True)  # why no cuda()?

        # compute output
        trans_output, rotation_output = model(input_var)
        trans_loss = pose_loss(trans_output, target_var[:, 0:3])
        rotation_loss = pose_loss(rotation_output, target_var[:, 3:]) * beta
        loss = trans_loss + rotation_loss

        # measure and record loss
        losses.update(loss.data[0], input.size(0))
        trans_losses.update(trans_loss.data[0], input.size(0))
        rotation_losses.update(rotation_loss.data[0], input.size(0))
        rotation_errors.update(rotation_error(rotation_output,
                                              target_var[:, 3:]).data[0], input.size(0))

    print('Test: [{0}]\t'
          'Loss ({loss.avg:.4f})\t'
          'Trans Loss ({trans_loss.avg:.4f})\t'
          'Rotation Loss ({rotation_loss.avg:.4f})\t'
          'Rotation Error ({rotation_error.avg:.4f})'.format(
        len(val_loader), loss=losses, trans_loss=trans_losses,
        rotation_loss=rotation_losses, rotation_error=rotation_errors)
    )

    return losses.avg, trans_losses.avg, rotation_losses.avg


def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'model_best.pth.tar')


def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 80 epochs"""
    lr = 1e-4 * (0.1 ** (epoch // 80))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def pose_loss(input, target):
    x = torch.norm(input - target, dim=1)  # dim=1???
    x = torch.mean(x)

    return x


def rotation_error(input, target):

    x1 = torch.norm(input, dim=1)
    x2 = torch.norm(target, dim=1)

    x1 = torch.div(input, torch.stack((x1, x1, x1, x1), dim=1))
    x2 = torch.div(target, torch.stack((x2, x2, x2, x2), dim=1))
    d = torch.abs(torch.sum(x1 * x2, dim=1))
    theta = 2 * torch.acos(d) * 180 / math.pi
    theta = torch.mean(theta)

    return theta


class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


if __name__ == '__main__':
    main()
