import os
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter

from SRGAN import *
from util import *
from data_loader import *

from torchvision import transforms

import argparse

## variable setting
parser = argparse.ArgumentParser(description="SRGAN parameter",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("--mode", default="train", choices=["train", "test"], type=str, dest="mode")
parser.add_argument("--train_continue", default="on", choices=["on", "off"], type=str, dest="train_continue")

parser.add_argument("--lr", default=1e-4, type=float, dest="lr")
parser.add_argument("--batch_size", default=8, type=int, dest="batch_size")
parser.add_argument("--num_epoch", default=300, type=int, dest="num_epoch")


parser.add_argument("--data_dir", default="./datasets/img_align_celeba", type=str, dest="data_dir")
parser.add_argument("--ckpt_dir", default="./checkpoint", type=str, dest="ckpt_dir")
parser.add_argument("--log_dir", default="./log", type=str, dest="log_dir")
parser.add_argument("--result_dir", default="./result", type=str, dest="result_dir")

parser.add_argument("--task", default="super_resolution", choices=["inpainting", "denoising", "super_resolution"], type=str, dest="task")
parser.add_argument('--opts', nargs='+', default=['bilinear', 4.0, 0], dest='opts')

parser.add_argument("--ny", default=320, type=int, dest="ny")
parser.add_argument("--nx", default=480, type=int, dest="nx")
parser.add_argument("--nch", default=3, type=int, dest="nch")
parser.add_argument("--nker", default=64, type=int, dest="nker")

parser.add_argument("--network", default="SRGAN", choices=["SRResNet", "SRGAN"], type=str, dest="network")

args = parser.parse_args()

mode = args.mode
train_continue = args.train_continue

lr = args.lr
batch_size = args.batch_size
num_epoch = args.num_epoch

data_dir = args.data_dir
ckpt_dir = args.ckpt_dir
log_dir = args.log_dir
result_dir = args.result_dir

task = args.task
opts = [args.opts[0], np.asarray(args.opts[1:]).astype(np.float)]

ny = args.ny
nx = args.nx
nch = args.nch
nker = args.nker

network = args.network

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# directory setting
result_dir_train = os.path.join(result_dir, 'train')
result_dir_val = os.path.join(result_dir, 'val')
result_dir_test = os.path.join(result_dir, 'test')

if not os.path.exists(result_dir_train):
    os.makedirs(os.path.join(result_dir_train, 'png'))
if not os.path.exists(result_dir_test):
    os.makedirs(os.path.join(result_dir_test, 'png'))
    os.makedirs(os.path.join(result_dir_test, 'numpy'))

## Train
if mode == 'train':
    transform_train = transforms.Compose([RandomCrop(shape=(ny, nx)), RandomFlip()])
    transform_val = transforms.Compose([RandomCrop(shape=(nx, ny))])

    dataset_train = Dataset(data_dir=data_dir, transform=transform_train, task=task, opts=opts)
    loader_train = DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=4)

    dataset_val = Dataset(data_dir=data_dir, transform=transform_val,  task=task, opts=opts)
    loader_val = DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=4)

    num_data_train = len(dataset_train)
    num_batch_train = np.ceil(num_data_train / batch_size)

    num_data_val = len(dataset_val)
    num_batch_val = np.ceil(num_data_val / batch_size)
else:
    transform_test = transforms.Compose([RandomCrop(shape=(ny, nx))])

    dataset_test = Dataset(data_dir=data_dir, transform=transform_test, task=task, opts=opts)
    loader_test = DataLoader(dataset_test, batch_size=batch_size, shuffle=False, num_workers=4)

    num_data_test = len(dataset_test)
    num_batch_test = np.ceil(num_data_test / batch_size)

## Network setting
if network == 'SRResNet':
    net = Generator(in_channels=nch, out_channels=nch, nker=nker)
    optim = torch.optim.Adam(net.parameters(), lr=lr, betas=(0.5, 0.999))

## Network setting
if network == 'SRGAN':
    netG = Generator(in_channels=100, out_channels=nch, nker=nker).to(device)
    netD = Discriminator(in_channels=nch, out_channels=1, nker=nker).to(device)

    # 네트워크의 모든 weights 초기화 (Normal(mean=0, standard deviation=0.02))
    init_weights(netG, init_type='normal', init_gain=0.02)
    init_weights(netD, init_type='normal', init_gain=0.02)

    ## Optimizer
    # optimizer의 momentum term B(1)값을 0.9(default) => 0.5
    optimG = torch.optim.Adam(netG.parameters(), lr=lr, betas=(0.5, 0.999))
    optimD = torch.optim.Adam(netD.parameters(), lr=lr, betas=(0.5, 0.999))


## Loss function
fn_loss = nn.MSELoss().to(device)

## variables setting
fn_tonumpy = lambda x: x.to('cpu').detach().numpy().transpose(0, 2, 3, 1)
fn_denorm = lambda x, mean, std: (x * std) + mean
fn_class = lambda x: 1.0 * (x > 0.5)

cmap = None

## SummaryWritter for Tensorboard
writer_train = SummaryWriter(log_dir=os.path.join(log_dir, 'train'))
writer_val = SummaryWriter(log_dir=os.path.join(log_dir, 'val'))

## TRAIN
st_epoch = 0

## SRResNet
if network == 'SRResNet':
    if mode == 'train':
        if train_continue == 'on':
            net, optim, st_epoch = load(ckpt_dir=ckpt_dir, net=net, optim=optim)
        
        for epoch in range(st_epoch+1, num_epoch+1):
            net.train()
            loss_mse = []

            for batch, data in enumerate(loader_train, 1):
                label = data['label'].to(device)
                input = data['input'].to(device)

                output = net(input)

                loss = fn_loss(output, label)
                loss.backward()

                optim.step()

                loss_mse += [loss.item()]

                print('TRAIN: EPOCH %04d / %04d | BATCH %04d / %04d | LOSS %.4f' %
                        (epoch, num_epoch, batch, num_batch_train, np.mean(loss_mse)))

                if batch % 20 == 0:
                    label = fn_tonumpy(label)
                    input = fn_tonumpy(input)
                    output = fn_tonumpy(output)

                    label = np.clip(label, a_min=0, a_max=1)
                    input = np.clip(input, a_min=0, a_max=1)
                    output = np.clip(output, a_min=0, a_max=1)

                    id = num_batch_train * (epoch - 1) + batch

                    plt.imsave(os.path.join(result_dir_train, 'png', '%04d_label.png' % id), label[0].squeeze(), cmap=cmap)
                    plt.imsave(os.path.join(result_dir_train, 'png', '%04d_input.png' % id), input[0].squeeze(), cmap=cmap)
                    plt.imsave(os.path.join(result_dir_train, 'png', '%04d_output.png' % id), output[0].squeeze(), cmap=cmap)

            writer_train.add_scalar('loss', np.mean(loss_mse), epoch)

            with torch.no_grad():
                net.eval()
                loss_mse = []
                
                for batch, data in enumerate(loader_val, 1):
                    label = data['label'].to(device)
                    input = data['input'].to(device)
                    output = net(input)

                    loss = fn_loss(output, label)
                    loss_mse += [loss.item()]

                    print('VALID: EPOCH %04d / %04d | BATCH %04d / %04d | LOSS %.4f' %
                            (epoch, num_epoch, batch, num_batch_val, np.mean(loss_mse)))

                    if batch % 20 == 0:
                        label = fn_tonumpy(label)
                        input = fn_tonumpy(input)
                        output = fn_tonumpy(output)

                        label = np.clip(label, a_min=0, a_max=1)
                        input = np.clip(input, a_min=0, a_max=1)
                        output = np.clip(output, a_min=0, a_max=1)

                        id = num_batch_val * (epoch - 1) + batch

                        plt.imsave(os.path.join(result_dir_val, 'png', '%04d_label.png' % id), label[0].squeeze(), cmap=cmap)
                        plt.imsave(os.path.join(result_dir_val, 'png', '%04d_input.png' % id), input[0].squeeze(), cmap=cmap)
                        plt.imsave(os.path.join(result_dir_val, 'png', '%04d_output.png' % id), output[0].squeeze(), cmap=cmap)

            writer_val.add_scalar('loss', np.mean(loss_mse), epoch)
## SRGAN
elif network == 'SRGAN':
    if mode == 'train':
        if train_continue == 'on':
            netG, netD, optimG, optimD, st_epoch = gan_load(ckpt_dir=ckpt_dir, netG=netG, netD=netD, optimG=optimG, optimD=optimD)

        for epoch in range(st_epoch+1, num_epoch+1):
            netG.train()
            netD.train()

            loss_G_train = []
            loss_D_real_train = []
            loss_D_fake_train = []

            for batch, data in enumerate(loader_train, 1):
                # forward pass
                label = data['label'].to(device)
                #input = torch.randn(label.shape[0], 100, 1, 1,).to(device) # (B, C, H, W)
                input = data['input'].to(device)

                output = netG(input)

                # backward netD
                set_requires_grad(netD, True)
                optimD.zero_grad()

                pred_real = netD(label) # True = torch.ones()
                pred_fake = netD(output.detach()) # False = torch.zeros()

                loss_D_real = fn_loss(pred_real, torch.ones_like(pred_real))
                loss_D_fake = fn_loss(pred_fake, torch.zeros_like(pred_fake))
                loss_D = (loss_D_real + loss_D_fake) / 2

                loss_D.backward()

                optimD.step()

                # backward netG
                set_requires_grad(netD, False)
                optimG.zero_grad()

                pred_fake = netD(output)

                loss_G = fn_loss(pred_fake, torch.ones_like(pred_fake))

                loss_G.backward()

                optimG.step()

                # loss function
                loss_G_train += [loss_G.item()]
                loss_D_real_train += [loss_D_real.item()]
                loss_D_fake_train += [loss_D_fake.item()]

                print("TRAIN: EPOCH %04d / %04d | BATCH %04d / %04d | GEN %.4f | DISC REAL: %.4f | DISC FAKE: %.4f"
                    % (epoch, num_epoch, batch, num_batch_train, np.mean(loss_G_train), np.mean(loss_D_real_train), np.mean(loss_D_fake_train)))

                if batch % 20 == 0:
                    # Tensorboard save
                    #output = fn_tonumpy(fn_denorm(output, mean=0.5, std=0.5)).squeeze()
                    output = np.clip(output, a_min=0, a_max=1)

                    id = num_batch_train * (epoch - 1) + batch

                    plt.imsave(os.path.join(result_dir_train, 'png', '%04d_output.png' % id), output[0].squeeze(), cmap=cmap)

                    writer_train.add_image('output', output, id, dataformats='NHWC')

            writer_train.add_scalar('loss_G', np.mean(loss_G_train), epoch)
            writer_train.add_scalar('loss_D_real', np.mean(loss_D_real_train), epoch)
            writer_train.add_scalar('loss_D_fake', np.mean(loss_D_fake_train), epoch)

            if epoch % 20 == 0:
                gan_save(ckpt_dir=ckpt_dir, netG=netG, netD=netD, optimG=optimG, optimD=optimD, epoch=epoch)

        writer_train.close()
    """# TEST MODE
    else:
        netG, netD, optimG, optimD, st_epoch = gan_load(ckpt_dir, netG=netG, netD=netD, optimG=optimG, optimD=optimD)

        with torch.no_grad():
            netG.eval()

            input = torch.randn(batch_size, 100, 1, 1).to(device)

            output = netG(input)

            output = fn_tonumpy(fn_denorm(output, mean=0.5, std=0.5))

            for j in range(output.shape[0]):
                id = j

                output_ = output[j]
                np.save(os.path.join(result_dir_test, 'numpy', '%04d_output.npy' % id), output_)

                output_ = np.clip(output_, a_min=0, a_max=1)
                plt.imsave(os.path.join(result_dir_test, 'png', '%04d_output.png' % id), output_, cmap=cmap)"""