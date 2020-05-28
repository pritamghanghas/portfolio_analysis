from .algofactory import *
from .utils import *
from .signals import *

##############################################################################
# Run backtest strategy on single instrument.
#
# @args
def raw_positions(
    buy:         pd.Series=None,    # Buy Signals
    sell:        pd.Series=None,    # Sell Signals
    short:       pd.Series=None,    # Short signals
    cover:       pd.Series=None,    # Cover signals
):
    # Whether long and short sides are enabled
    long_df    = None
    short_df   = None
    all_df     = None
    smask      = []
    run_mode   = None

    # Check buy/sell signals
    if buy is not None:
        assert sell is not None, '>> ERROR:: "sell" should be valid, when "buy" signal is valid.'
        buy        = set_buy(buy)
        sell       = set_sell(sell)
        long_df    = pd.concat([buy, sell], axis=1)
        smask     += [SIGNAL.BUY, SIGNAL.SELL]
        run_mode   = 'long'
    # endif

    # Check short/cover signals
    if short is not None:
        assert cover is not None, '>> ERROR:: "cover" should be valid, when "short" signal is valid.'
        short      = set_short(short)
        cover      = set_cover(cover)
        short_df   = pd.concat([short, cover], axis=1)
        smask     += [SIGNAL.SHORT, SIGNAL.COVER]
        run_mode   = 'any' if run_mode == 'long' else 'short'
    # endif

    if long_df is not None and short_df is not None:
        all_df = pd.concat([long_df, short_df], axis=1)
    elif long_df is not None:
        all_df = long_df
    elif short_df is not None:
        all_df = short_df
    # endif

    print('>> Using signal mask {}.'.format(smask))
    pos     = signals_to_positions(all_df, mode=run_mode, mask=smask, use_vec=True).astype('float')

    return pos
# enddef
