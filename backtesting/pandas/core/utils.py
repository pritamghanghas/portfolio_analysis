import pandas as pd
import numpy as np
import quantstats as qs
import re
import matplotlib.pyplot as plt
from   typing import AnyStr, Callable
from   modules.utils import *

############################################################
# Constants
class SIGNAL:
    BUY    = 'Buy'
    SELL   = 'Sell'
    SHORT  = 'Short'
    COVER  = 'Cover'
# endclass

# Various kinds of Masks, depending on the naming convention used to define
# Signals
SIGNAL_MASK        = (SIGNAL.BUY, SIGNAL.SELL, SIGNAL.SHORT, SIGNAL.COVER)
SIGNAL_MASK2       = (SIGNAL.BUY, SIGNAL.SELL, SIGNAL.SELL, SIGNAL.BUY)
SIGNAL_MASK_LONG   = (SIGNAL.BUY, SIGNAL.SELL)
SIGNAL_MASK_SHORT  = (SIGNAL.SHORT, SIGNAL.COVER)
SIGNAL_MASK_SHORT2 = (SIGNAL.SELL, SIGNAL.BUY)

# Some keys
KEY_SIGNALS     = 'signals'
KEY_POSITIONS   = 'positions'
KEY_SLIPPAGE    = 'slippage'
KEY_RUNMODE     = 'run_mode'
KEY_PRICES      = 'prices'
KEY_RETURNS     = 'returns'
KEY_STRATEGY    = 'strategy'
KEY_STRATPARAMS = 'strategy_params'
KEY_NPOINTS     = 'points'

#############################################################
# Signal utility functions
def crossover(s1, s2, lag=1):
    return (s1 > s2) & (s1.shift(lag) < s2.shift(lag))
# enddef

def crossunder(s1, s2, lag=1):
    return (s1 < s2) & (s1.shift(lag) > s2.shift(lag))
# enddef

# shift parameter takes into account that we always buy or sell
# (i.e. take positions) on next bar
def set_buy(s, shift=True):
    s = s.shift().fillna(False) if shift else s
    s.name = SIGNAL.BUY
    return s
# enddef
def set_sell(s, shift=True):
    s = s.shift().fillna(False) if shift else s
    s.name = SIGNAL.SELL
    return s
# enddef
def set_short(s, shift=True):
    s = s.shift().fillna(False) if shift else s
    s.name = SIGNAL.SHORT
# enddef
def set_cover(s, shift=True):
    s = s.shift().fillna(False) if shift else s
    s.name = SIGNAL.COVER
# enddef

#############################################################
# Pandas utility functions
def fillna(df):
    df = df.fillna(0)
    df = df.replace([np.inf, -np.inf], 0)
    return df
# enddef

def sanitize_datetime(df):
    df.index = pd.to_datetime(df.index)
    return df
# enddef

################################################################
# For handling price data
class Price(object):
    OPEN     = 'open'
    CLOSE    = 'close'
    HIGH     = 'high'
    LOW      = 'low'
    VOLUME   = 'volume'
    OHLC     = [OPEN, HIGH, LOW, CLOSE]
    OHLCV    = OHLC + [VOLUME]
    LIST_ALL = OHLCV + ['all']
    COL_MAP  = {'o': OPEN, 'h': HIGH, 'l': LOW, 'c':CLOSE, 'v':VOLUME}

    def __c_columns_to_keys(self, columns):
        cols = list(columns)
        assert len(set(cols) - set(self.COL_MAP.keys())) == 0, 'Invalid columns "{}"'.format(columns)
        return [self.COL_MAP[k] for k in cols]
    # enddef

    def __c_columns_heur1_match(self, columns, df, en=True):
        if en:
            cols_assumed = [x.lower() for x in list(columns)]
            cols_passed  = [x[0].lower() for x in df.columns.to_list()]
            assert cols_assumed == cols_passed, '>> Passed columns="{}" doesnot seem to match dataframe columns="{}"'.format(columns, df.columns)
        # endif
    # enddef

    def __init__(self, df: pd.DataFrame, columns: str='ohlcv', match_cols: bool=True):
        # Run a heuristic check on columns
        self.__c_columns_heur1_match(columns, df, match_cols)
        # Print some info
        print('>> Assumed columns="{}", CSV columns="{}". Please change if not applicable !!'.format(list(columns), df.columns.to_list()))
        # Assign data
        self.data = df
        # New column map
        new_cols = self.__c_columns_to_keys(columns)
        # Rename columns
        self.data.set_axis(new_cols, axis='columns', inplace=True)
        # Change index to datetime
        self.data.index = pd.to_datetime(self.data.index)
    # enddef

    def __getitem__(self, key):
        if key in self.OHLCV:
            return self.data[key]
        elif key == 'all':
            return self.data
        else:
            raise ValueError('Unsupported key {} in Price[]. Supported keys are = {}'.format(key, self.OHLCV))
        # endif
    # enddef

    def __repr__(self):
        return self.data.__repr__()
    # enddef

    def __str__(self):
        return self.data.__str__()
    # enddef

    @classmethod
    def from_df(cls, df, columns='ohlcv'):
        return cls(df, columns=columns)
    # enddef

    @classmethod
    def from_csv_file(cls, csv_file, columns='ohlcv'):
        return cls.from_df(pd.read_csv(csv_file, index_col=0), columns=columns)
    # enddef

    def resample(self, time_frame):
        return Price.from_df(self.data.resample(time_frame).agg({
            self.OPEN  : 'first',
            self.HIGH  : 'max',
            self.LOW   : 'min',
            self.CLOSE : 'last',
            self.VOLUME: 'sum' }), columns=self.OHLCV)
    # enddef
# endclass

############################################################
# Singnals to Position Generator
def _take_position_any(sig, pos, long_en, long_ex, short_en, short_ex):
    # check exit signals
    if pos != 0:  # if in position
        if pos > 0 and sig[long_ex]:  # if exit long signal
            pos -= sig[long_ex]
        elif pos < 0 and sig[short_ex]:  # if exit short signal
            pos += sig[short_ex]
        # endif
    # endif
    # check entry (possibly right after exit)
    if pos == 0:
        if sig[long_en]:
            pos += sig[long_en]
        elif sig[short_en]:
            pos -= sig[short_en]
        # endif
    # endif

    return pos
# enddef

def _take_position_long(sig, pos, long_en, long_ex):
    # check exit signals
    if pos != 0:  # if in position
        if pos > 0 and sig[long_ex]:  # if exit long signal
            pos -= sig[long_ex]
        # endif
    # endif
    # check entry (possibly right after exit)
    if pos == 0:
        if sig[long_en]:
            pos += sig[long_en]
        # endif
    # endif

    return pos
# enddef

def _take_position_short(sig, pos, short_en, short_ex):
    # check exit signals
    if pos != 0:  # if in position
        if pos < 0 and sig[short_ex]:  # if exit short signal
            pos += sig[short_ex]
        # endif
    # endif
    # check entry (possibly right after exit)
    if pos == 0:
        if sig[short_en]:
            pos -= sig[short_en]
        # endif
    # endif

    return pos
# enddef

def _check_signals_to_positions_args(mode, mask):
    mode_list = ['long', 'short', 'any']

    assert mode in mode_list, 'ERROR:: mode should be one of {}'.format(mode_list)
    if mode == 'any':
        assert len(mask) == 4 , 'ERROR:: in "any" mode, mask should be of 4 keys.'
    # endif
    assert len(mask) == 2 or len(mask) == 4, 'ERROR:: mask should be of 2 or 4 keys.'
# enddef

def signals_to_positions(signals, init_pos=0, mode='any', mask=SIGNAL_MASK, shift=False):
    # Checks
    _check_signals_to_positions_args(mode, mask)

    pos = init_pos
    ps  = pd.Series(0., index=signals.index)

    if mode == 'any':
        long_en, long_ex, short_en, short_ex = mask
        for t, sig in signals.iterrows():
            pos   = _take_position_any(sig, pos, long_en, long_ex, short_en, short_ex)
            ps[t] = pos
        # endfor
    elif mode == 'long':
        long_en, long_ex = mask
        for t, sig in signals.iterrows():
            pos   = _take_position_long(sig, pos, long_en, long_ex)
            ps[t] = pos
        # endfor
    elif mode == 'short':
        short_en, short_ex = mask
        for t, sig in signals.iterrows():
            pos   = _take_position_short(sig, pos, short_en, short_ex)
            ps[t] = pos
        # endfor
    # endif

    return ps.shift() if shift else ps
# enddef

########################################################
# Signals visualization
def _extract_decision_signals(signals):
    sig_columns = signals.columns
    aux_sigcols = list(set(sig_columns) - set(SIGNAL_MASK))
    psig_list   = list(set(sig_columns) - set(aux_sigcols))
    psigs       = signals[psig_list]
    auxsigs     = signals[aux_sigcols]
    return psigs, auxsigs
# enddef

def _split_auxiliary_signals(aux_signals):
    asig_cols   = aux_signals.columns
    # Search for unique signals to be plotted on same plane
    sigs_dict   = {'ext': []}
    for asig_t in asig_cols:
        _m = re.search("^([\d]+)_", asig_t )
        if _m:
            _m = int(_m.groups()[0])
            if _m not in sigs_dict:
                sigs_dict[_m] = []
            # endif
            sigs_dict[_m].append(asig_t)
        else:
            sigs_dict['ext'].append(asig_t)
        # endif
    # endfor

    sigs_dict = {k: aux_signals[v] for k,v in sigs_dict.items() if len(v) !=0}
    return list(sigs_dict.values())
# enddef

def plot_signals(signals, sharex='all', dec_sig_ratio=0.2):
    psigs, aux_sigs = _extract_decision_signals(signals)
    aux_sig_cols    = aux_sigs.columns
    aux_sigs_list   = _split_auxiliary_signals(aux_sigs)
    psigs           = psigs.applymap(lambda x: 1 if x is True else 0)

    plots_len   = 1 + len(aux_sigs_list)
    oth_ax_rs   = (1-dec_sig_ratio)/(plots_len-1)
    ratios      = [oth_ax_rs] * (plots_len-1) + [dec_sig_ratio]
    fig, axes   = plt.subplots(plots_len, sharex=sharex, gridspec_kw={'height_ratios' : ratios})
    ax_ctr      = 0

    for aux_sig_t in aux_sigs_list:
        aux_sig_t.plot(ax=axes[ax_ctr])
        ax_ctr += 1
    # endfor
    psigs.plot(ax=axes[ax_ctr])
    return fig
# enddef

########################################################
# Calculate returns for a portfolio of assets given their
# individual returns
def calculate_portfolio_returns(returns, weights_list, log_returns=True):
    assert isinstance(returns, pd.DataFrame), 'ERROR::: returns should be a pandas dataframe of individual asset returns'
    assert len(returns.columns) == len(weights_list), 'ERROR:: Dimensions of weights_list should match that of number of columns in returns.'

    crets = np.log(np.dot(np.exp(returns), weights_list)) if log_returns else np.dot(returns, weights_list)
    return pd.Series(crets, index=returns.index)
# enddef

########################################################
# Slippage calculator
# NOTES:
# If nrets is of type log then :-
#     r = ln(y/x), without any slippage
# For slippage s, we have
#     r = ln(y/x(1+s)) for long and
#     r = ln(y/x(1-s)) for short, thus
#     r = ln(y/x) - ln(1+s) for long
#     r = ln(y/x) - ln(1-s) for short
# @args :-
#     pos        -> array of positions, 1 for long, -1 for short, 0 for out of market
#     rets       -> per bar returns of closing prices (daily returns if timeframe is daily)
#     slip       -> Slippage value (in %cenatge of closing prices if slip_perc=True)
#     ret_type   -> specify whether rets is normal returns or log returns
#     slip_perc  -> if True, slip is assumed as a %, else a fixed value in points
#     price      -> closig prices (only used when slippage is fixed.)
def apply_slippage(pos, rets, slip, ret_type='log', slip_perc=True, price=None):
    # Some checks
    if slip_perc == False:
        assert price is not None, 'ERROR:: price should not be None when slippage type is fixed.'
    # endif

    # Print information about how slippage is being calculated
    print('>> Using slippage {}{}'.format(slip, '%' if slip_perc else 'pts'))

    # Create new pandas df of rets and pos
    _df = pd.DataFrame(index=pos.index)
    _df['pos']   = pos
    _df['rets']  = rets
    _df['pos_d'] = pos.diff()
    if not price.empty:
        _df['price'] = price
    # endif

    # Apply slippage
    if ret_type == 'log':
        if slip_perc:
            pos_slip = -np.log(1 + slip*0.01)
            neg_slip = -np.log(1 - slip*0.01)
            retss    = pos * _df.apply(lambda x: x.rets + pos_slip if x.pos_d > 0 else \
                           x.rets + neg_slip if x.pos_d < 0 else x.rets, axis=1)
        else:
            retss    = pos * _df.apply(lambda x: x.rets - np.log(1 + slip/x.price) if x.pos_d > 0 else \
                           x.rets - np.log(1 - slip/x.price) if x.pos_d < 0 else x.rets, axis=1)
        # endif
    else:
        raise ValueError('ERROR:: Only ret_type="log" is supported !!')
        #slip_u   = 0.01 * slip
        #retss    = pos * _df.apply(lambda x: (x.rets - slip_u)/(1 + slip_u) if x.pos_d > 0 else (x.rets + slip_u)/(1 - slip_u) if x.pos_d < 0 else x.rets, axis=1)
    # endif
    return retss
# enddef

# Wrapper over apply_slippage. It accepts slippage in compact string form.
# Either in 'X', 'X%' or 'Xpts'
def apply_slippage_v2(pos, rets, slip, ret_type='log', price=None):
    slippage, slip_perc = extract_slippage(slip)
    return apply_slippage(pos, rets, slippage, ret_type, slip_perc, price)
# enddef

# Some utils
def extract_slippage(slip):
    assert isstring(slip), 'slippage={} should be of type string in form of X, X% or Xpts, where x is a float.'.format(slip)
    slip = slip.replace(' ', '')
    
    if slip[-1] == '%':
        return (float(slip[:-1]), True)
    elif slip[-3:].lower() == 'pts':
        return (float(slip[:-3]), False)
    else:
        try:
            return (float(slip), False)
        except:
            raise ValueError('slippage={} not in desired format X, X% or Xpts where X is a float'.format(slip))
        # endtry
    # endif
# enddef

#########################################################
# Quantstrat based tearsheet generator
def generate_tearsheet(rets, out_file):
    qs.reports.html(rets, output=out_file)
# enddef

def generate_basic_report(rets):
    qs.reports.metrics(rets)
# enddef
