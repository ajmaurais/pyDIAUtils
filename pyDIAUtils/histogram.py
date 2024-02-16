
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np


def histogram(dat, xlab, ylab='Count', limits=None, fname=None, dpi=250):
    fig, ax = plt.subplots(1, 1, figsize = (6, 4), dpi=dpi)
    ax.hist(dat, bins = 100)
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)

    if limits:
        plt.xlim(limits)

    if fname:
        plt.savefig(fname)
    else:
        plt.show()
    plt.close()


def box_plot(data, ylab, xlab='Acquisition number', fname=None, hline=None, limits=None, dpi=250):

    # init plot
    fig, ax = plt.subplots(1, 1, figsize = (10, 4), dpi=dpi)

    # plot outliers as scatter
    for i, c in enumerate(data.columns):
        y = data[c]
        q3, q1 = np.percentile(y, [75, 25])
        iqr = q3 - q1
        outliers = y[(y > q3 + (1.5 * iqr)) | (y < q1 - (1.5 * iqr))]
        x = np.random.normal(i + 1, 0.04, size=len(outliers))
        ax.scatter(x, outliers, c = 'black', s = 0.3, alpha = 0.5)

    if hline is not None:
        plt.axhline(y=hline, color='black', linestyle=':', linewidth=1)

    # plot boxes
    ax.boxplot(data, showfliers=False)

    if limits:
        plt.ylim(limits)

    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)
    n_cols = len(data.columns)
    plt.xticks(np.linspace(1, n_cols, num=min(6, n_cols), dtype=int),
               np.linspace(0, n_cols - 1, num=min(6, n_cols), dtype=int))

    if fname:
        plt.savefig(fname)
    else:
        plt.show()
    plt.close()

