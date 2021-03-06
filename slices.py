"""
fraction_host.py
2015 Brandon Mechtley
Reuman Lab, Kansas Biological Survey

Plot fraction of synchrony in the host that is a result of host synchronizing
effects (migration, Moran). Fraction of synchrony in this case is defined as
the Pearson correlation coefficient between the two host populations in either
patch without any parasitoid synchronizing influences (i.e. Spp=0, mp=0) divided
by the correlation between the two hosts with all synchronizing influences.

TODO: Try to find a reasonable bounding box over which to average these things.
"""

import os
import sys
import time
import glob
import json
import cPickle
import multiprocessing
from itertools import combinations_with_replacement, izip

import numpy as np
import matplotlib.cm
import matplotlib.colors
import matplotlib.pyplot as pp

import models
import utilities

model = models.parasitism.get_model('nbd(2)')

    
def fraction_synchrony(params):
    """
    Compute the fraction of synchrony between patches for which the host is
    responsible using different metrics.

    TODO: Allow caching of spectra.
    TODO: Return fraction for which different populations are responsible.
    TODO: Optimize.
    TODO: Allow for different parameter ranges.

    :param params: model parameter dictionary. Contains "num" and "den" keys
        that contain parameter keys.
    :return: dictionary of metric: fraction pairs.
    """

    correlations = {
        term: models.utilities.correlation(
            model.calculate_covariance(
                models.parasitism.sym_params({
                    k: v for k, v in p.iteritems()
                    if k not in ['Sp', 'Chh', 'Cpp']
                }), utilities.noise_cov(p)
            )
        )
        for term, p in params.iteritems()
    }

    if np.any(np.isnan(np.array([correlations['num'], correlations['den']]))):
        correlations['ratio'] = np.full_like(correlations['num'], np.nan())
    else:
        correlations['ratio'] = correlations['num'] / correlations['den']

    return correlations


def process_products(opts):
    """
    Parallel worker for computing fraction of average synchrony. Used by
    make_products.

    :param opts: (dict): dictionary of input parameters, including keys:
        params: (dict) parameter dictionary of the form
            {name: {default: default, range: (low, high), res: resolution}.
        k1: (str) Y parameter name.
        k2: (str) X parameter name.
    :return: (R1, R2) dimensional list (not array) of dictionaries where each
        key is a different synchrony metric, e.g. fracavgsync. See
        fraction_synchrony for more info.
    """

    params, cacheprefix, k1, k2 = opts
    cachepath = '%s-%s-part.pickle' % (cacheprefix, utilities.paramhash(opts))

    varyingkeys = [k for k in params if len(params[k]['range']) > 1]
    defaults = {k: v['default'] for k, v in params.iteritems()}
    r1, r2 = [params[k]['range'] for k in [k1, k2]]

    keycombos = list(combinations_with_replacement(varyingkeys, 2))
    strargs = '%d / %d (%s, %s) (PID %d).' % (
        keycombos.index((k1, k2)) + 1, len(keycombos), k1, k2, os.getpid()
    )

    result = None

    if os.path.exists(cachepath):
        print 'Loading', strargs
        result = cPickle.load(open(cachepath))
    else:
        print 'Processing', strargs

        btime = time.clock()

        fracsync = lambda a, b: fraction_synchrony(dict(
            num=utilities.dict_merge(defaults, {
                k1: a, k2: b,
                'Spp': 0, 'mp': 0, 'Cpp': 0
            }),
            den=utilities.dict_merge(defaults, {k1: a, k2: b})
        ))

        if k1 != k2:
            result = [[fracsync(v1, v2) for v2 in r2] for v1 in r1]
            result = {
                k: np.array([[cell[k] for cell in row] for row in result])
                for k in result[0][0].keys()
            }
        else:
            result = [fracsync(v1, v1) for v1 in r1]
            result = {
                k: np.array([cell[k] for cell in result])
                for k in result[0].keys()
            }

        result['time'] = time.clock() - btime
        print '\t\t\t\t\tCompleted (%.3fs)' % (result['time']), strargs

        btime = time.clock()
        cPickle.dump(result, open(cachepath, 'w'))
        print '\t\t\t\t\tSaved (%.3f)' % (time.clock() - btime), strargs

    return result


def make_products(
        params=None, processes=multiprocessing.cpu_count(), cacheprefix=''
):
    """
    Compute fraction of synchrony metrics across combinations of values for each
    pair of model parameters.

    :param params: (dict) Parameter dictionary, of the form
        {name: {default: default, range: (low, high), res: resolution}.
    :param processes: (int) number of processes to use for computation.
    :param cacheprefix: (str) prefix for cached pickle files. Hash of
        parameters will be appended for each process.
    :return: (P, P, R1, R2) dimensional list (not array) of dictionaries where
        each key is a different synchrony metric, e.g. fracavgsync. See
        fraction_synchrony for more info.
    """

    varyingkeys = [k for k in params if len(params[k]['range']) > 1]
    keyproduct = list(combinations_with_replacement(varyingkeys, 2))

    # Returns an array of dictionaries, each containing a two-dimensional array
    # with the different metrics returned by fraction_synchrony across the
    # combination of each pair of varying parameters.
    cachepath = '%s-products.pickle' % cacheprefix
    if not os.path.exists(cachepath):
        print 'Computing with %d processes.' % processes
        btime = time.clock()
        products = utilities.multipool(
            process_products,
            [(params, cacheprefix) + ks for ks in keyproduct],
            processes=processes
        )
        print 'Finished computing ratios (%.3fs).' % (time.clock() - btime)
        cPickle.dump(products, open(cachepath, 'w'))
        print 'Saved %s.' % cachepath
        for d in glob.glob('%s-*-part.pickle' % cacheprefix):
            os.remove(d)
    else:
        print 'Loading %s.' % cachepath
        products = cPickle.load(open(cachepath))

    # Restructure so we have a dictionary with fraction_synchrony metrics as
    # keys and lists of two-dimensional arrays of their values across the
    # combination of each pair of varying parameters.
    products = {k: [p[k] for p in products] for k in products[0].keys()}

    # Finally, return a dict such that each fraction_synchrony metric key is
    # associated with a (K, K, N, N) array, where K is the number of varying
    # keys and N is the parameter resolution.
    return {
        k: [
            [
                [
                    x for i, x in enumerate(v)
                    if (keyproduct[i][0] == k1 and keyproduct[i][1] == k2)
                    or (keyproduct[i][0] == k2 and keyproduct[i][1] == k1)
                ][0]
                for k2 in varyingkeys
            ] for k1 in varyingkeys
        ]
        for k, v in products.iteritems()
    }


def plot_fracsync(params=None, metric=None, filename=None, metricname=""):
    """
    Plot fraction of host synchrony due to host effects across combinations of
    values for each pair of model parameters.

    :param params: (dict) Parameter dictionary, of the form
        {name: {default: default, range: (low, high), res: resolution}. Should
        be the same dictionary used to produce the products parameter.
    :param metric: (str) metric to plot. Otherwise, plot all metrics.
    :param products: (list) (P, P, R1, R2) dimensional list (not array)
        containing dictionaries where each key is a different synchrony metric,
        e.g. fracavgsync. See fraction_synchrony for more info.
    :param filename: (str) Output filename for plot.
    :param metricname: (str) descriptive name of the metric to plot.
    """

    # Get fraction of host synchrony from host effects for all combinations
    # parameters that vary over more than one value (res > 1).
    vkeys = [k for k in params.iterkeys() if len(params[k]['range']) > 1]
    n = len(vkeys)

    # Get minimum and maximum values.
    values = np.concatenate([
        np.concatenate([
            metric[i][j].flatten() for j in range(len(metric[i]))
        ]).flatten() for i in range(len(metric))
    ]).flatten()

    vmin, vmax = np.real(np.nanmin(values)), np.real(np.nanmax(values))
    cmaps = [matplotlib.cm.get_cmap(cm) for cm in ['cubehelix', 'gnuplot2']]

    fig, subplots = pp.subplots(n, n, figsize=(5 * n + 5, 3.75 * n + 5))
    fig.suptitle('Frac. avg. sync. no para moran/dispersal / all effects')

    # i is row (y axis), j is column (x axis)
    for (i, ki, si, li), (j, kj, sj, lj) in combinations_with_replacement(
        zip(
            range(len(vkeys)),
            vkeys,
            [models.parasitism.symbols[k] for k in vkeys],
            [models.parasitism.labels[k] for k in vkeys]
        ),
        2
    ):
            ri, rj = params[ki]['range'], params[kj]['range']
            di, dj = params[ki]['default'], params[kj]['default']

            # If there is only one varying key, subplots(1, 1, ...) returns
            # just the first axes rather than a multidimensional list.
            try:
                ax = subplots[n - i - 1][n - j - 1]
            except TypeError:
                ax = subplots

            if i != j:
                subplots[i][j].set_axis_off()
                flat = metric[i][j].flatten()
                percs = [25, 50, 75]
                percvals = [np.percentile(flat, q) for q in percs]

                # 1. Plot fraction of average synchrony.
                fill_contour = ax.contourf(
                    rj, ri, np.real(metric[i][j]), 128,
                    vmin=vmin, vmax=vmax if vmax < 1 else 1, cmap=cmaps[0]
                )
                fill_contour.cmap.set_over((0, 0, 0, 0))
                fill_contour2 = None

                if vmax > 1:
                    fill_contour2 = ax.contourf(
                        rj, ri, np.real(metric[i][j]), 128,
                        vmin=1, vmax=vmax, cmap=cmaps[1]
                    )
                    fill_contour2.cmap.set_under((0, 0, 0, 0))

                # 2. Plot contours.
                line_contour = ax.contour(
                    rj, ri, metric[i][j],
                    colors=[
                        tuple([np.round(1.0 - np.mean(
                            cmaps[x >= 1](np.interp(x, [vmin, 1], [0, 1]))[:3]
                        ))]*3) + (1.0,)
                        for x in percvals
                    ],
                    levels=list(percvals),
                    linestyles=['dotted', 'dashed', 'solid']
                )

                # 3. Axes.
                ax.set_xlabel('$%s$ (%s)' % (sj, lj))
                ax.set_ylabel('$%s$ (%s)' % (si, li))
                ax.axvline(dj, color='pink', ls=':', lw=2)
                ax.axhline(di, color='pink', ls=':', lw=2)
                ax.set_xlim(rj[0], rj[-1])
                ax.set_ylim(ri[0], ri[-1])
                ax.tick_params(axis='both', which='major', labelsize=8)

                # 4. Labels.
                colorbar = pp.colorbar(fill_contour, ax=ax, spacing='uniform')
                colorbar.ax.tick_params(labelsize=8)

                if fill_contour2 is not None:
                    colorbar2 = pp.colorbar(
                        fill_contour2, cax=colorbar.ax, spacing='uniform'
                    )
                    colorbar2.ax.tick_params(labelsize=8)

                ax.clabel(line_contour, inline=1, fontsize=8, fmt={
                    percval: '%.2f (%d\\%%)' % (percval, perc)
                    for percval, perc in izip(percvals, percs)
                })
            else:
                ax.plot(ri, np.real(metric[i][j]), label=metricname)

                lineprops = dict(color='r', ls=':')
                ax.axvline(di, label='origin', **lineprops)
                ax.axhline(
                    np.interp(di, ri, np.real(metric[i][j])), **lineprops
                )

                ax.set_xlabel('$%s$ (%s)' % (si, li))
                ax.set_ylabel(metricname)
                ax.set_xlim(min(ri), max(ri))
                ax.set_ylim(min(metric[i][j]), max(metric[i][j]))
                ax.tick_params(axis='both', which='major', labelsize=8)
                ax.legend()

    pp.subplots_adjust(
        hspace=0.4, wspace=0.4, left=0.05, bottom=0.05, top=0.95, right=0.95
    )

    pp.savefig(filename, dpi=240)


def main():
    """Where the action is."""

    configpath = sys.argv[1]
    configdir, configfile = os.path.split(configpath)
    configname = os.path.splitext(configfile)[0]
    config = json.load(open(configpath))

    args, params = config['args'], config['params']

    for p in params.itervalues():
        if 'range' in p:
            p['range'] = np.linspace(
                p['range'][0], p['range'][1], args['resolution']
            )
        elif 'default' in p:
            p['range'] = [p['default']]

    products = make_products(
        params=params,
        processes=max(
            1, args.get('processes', multiprocessing.cpu_count() - 1)
        ),
        cacheprefix=os.path.join(configdir, configname)
    )

    metrics = {
        k: [
            [pj[:, :, 0, 1] if pj.ndim == 4 else pj[:, 0, 1] for pj in pi]
            for pi in v
        ]
        for k, v in products.iteritems() if k != 'time'
    }

    for k, v in metrics.iteritems():
        if k != 'time':
            plotpath = os.path.join(configdir, '%s-%s.png' % (configname, k))
            print 'Plotting %s.' % plotpath
            plot_fracsync(params, v, plotpath, k)

if __name__ == '__main__':
    main()
