"""
Extension for nexsci queries.

========== ==============================================
**Author** Christina Hedges
**Email**  christina.l.hedges@nasa.gov
**Date**   November 1, 2019
========== ==============================================

"""
import pandas as pd
import numpy as np
import os
import datetime
import astropy.units as u
from glob import glob
from warnings import warn

from ... import PACKAGEDIR
from ... import Secondary, Primary, System, Map


class DataRetrievalFailure(Exception):
    """Raised if data can't be retrieved from online database
    """

    pass


def from_nexsci(name, limb_darkening=[0.4, 0.2]):
    """Returns a starry system with properties of system

    Parameters
    ----------
    name : str
        Name of system to retrieve. e.g. 'K2-43' or 'K2-43b'

    Returns
    -------
    sys : :py:class:`starry.System`
        Starry system using planet parameters from nexsci
    """
    df = _get_nexsci_data()
    if name is "random":
        system_list = (
            df[
                [
                    "pl_hostname",
                    "pl_letter",
                    "pl_orbper",
                    "pl_trandep",
                    "pl_radj",
                ]
            ]
            .dropna()["pl_hostname"]
            .unique()
        )
        name = np.random.choice(system_list)
        warn("Randomly selected {}".format(name))
        df = df[df.pl_hostname == name].reset_index(drop=True)
    else:
        sname = name.lower().replace("-", "").replace(" ", "")
        if np.any([name.endswith(i) for i in "bcdefghijklmnopqrstuvwxyz"]):
            df = df[(df.stripped_name + df.pl_letter) == sname].reset_index(
                drop=True
            )
        else:
            df = df[(df.stripped_name) == sname].reset_index(drop=True)
        if len(df) == 0:
            raise ValueError("{} does not exist at NExSci".format(name))

    m = df.iloc[0].st_mass
    if ~np.isfinite(m):
        m = 1
        warn("Stellar mass is NaN, setting to 1.")

    star = Primary(Map(udeg=len(limb_darkening), L=1), r=1, m=m)
    for idx in range(len(limb_darkening)):
        star.map[idx + 1] = limb_darkening[idx]
    planets = []
    for idx, d in df.iterrows():
        for key in ["pl_orbper", "pl_tranmid", "pl_radj"]:
            if ~np.isfinite(d[key]):
                warn(
                    "{} is not set for {}{}, planet will be skipped".format(
                        key, d.pl_hostname, d.pl_letter
                    )
                )
        r = np.asarray(d.pl_radj * u.jupiterRad.to(u.solRad)) / np.asarray(
            d.st_rad
        )

        planet = Secondary(
            Map(L=0),
            porb=d.pl_orbper,
            t0=d.pl_tranmid,
            r=r,
            inc=d.pl_orbincl,
            ecc=d.pl_eccen,
            w=d.pl_orblper,
        )
        planets.append(planet)
    sys = System(star, *planets)
    return sys


def _fill_data(df):
    """Takes a dataframe of nexsci data and fills in NaNs with sane defaults.

    Parameters
    ----------
    df : pandas.DataFrame
        Dataframe of planet parameters from nexsci

    Returns
    -------
    clean_df : pandas.DataFrame
        Dataframe of planet parameters from nexsci, with NaNs replaced.
    """
    nan = ~np.isfinite(df.pl_orbincl)
    df.loc[nan, ["pl_orbincl"]] = np.zeros(nan.sum()) + 90

    nan = ~np.isfinite(df.pl_eccen)
    df.loc[nan, ["pl_eccen"]] = np.zeros(nan.sum())

    nan = ~np.isfinite(df.pl_orblper)
    df.loc[nan, ["pl_orblper"]] = np.zeros(nan.sum())

    # Fill in missing trandep
    nan = ~np.isfinite(df.pl_trandep)
    trandep = (
        np.asarray(df.pl_radj * u.jupiterRad.to(u.solRad))
        / np.asarray(df.st_rad)
    ) ** 2
    df.loc[nan, ["pl_trandep"]] = trandep[nan]
    return df


def _retrieve_online_data(guess_masses=False):
    """Queries nexsci database and returns a dataframe of planet data.
    """
    NEXSCI_API = "http://exoplanetarchive.ipac.caltech.edu/cgi-bin/nstedAPI/nph-nstedAPI"
    try:
        # Planet table
        planets = pd.read_csv(
            NEXSCI_API + "?table=planets&select=pl_hostname,pl_letter,"
            "pl_disc,ra,dec,pl_trandep,pl_tranmid,pl_tranmiderr1,"
            "pl_tranmiderr2,pl_tranflag,pl_trandur,pl_pnum,pl_k2flag,"
            "pl_kepflag,pl_facility,pl_orbincl,pl_orbinclerr1,pl_orbinclerr2,"
            "pl_orblper,st_mass,st_masserr1,st_masserr2,st_rad,st_raderr1,"
            "st_raderr2,st_teff,st_tefferr1,st_tefferr2,st_optmag,st_j,st_h",
            comment="#",
        )
        # Composite table
        composite = pd.read_csv(
            NEXSCI_API + "?table=compositepars&select=fpl_hostname,fpl_letter,"
            "fpl_smax,fpl_smaxerr1,fpl_smaxerr2,fpl_radj,fpl_radjerr1,"
            "fpl_radjerr2,fpl_bmassj,fpl_bmassjerr1,fpl_bmassjerr2,"
            "fpl_bmassprov,fpl_eqt,fpl_orbper,fpl_orbpererr1,fpl_orbpererr2,"
            "fpl_eccen,fpl_eccenerr1,fpl_eccenerr2,fst_spt",
            comment="#",
        )
        # Rename columns
        composite.columns = [
            "pl_hostname",
            "pl_letter",
            "pl_orbsmax",
            "pl_orbsmaxerr1",
            "pl_orbsmaxerr2",
            "pl_radj",
            "pl_radjerr1",
            "pl_radjerr2",
            "pl_bmassj",
            "pl_bmassjerr1",
            "pl_bmassjerr2",
            "pl_bmassprov",
            "pl_eqt",
            "pl_orbper",
            "pl_orbpererr1",
            "pl_orbpererr2",
            "pl_eccen",
            "pl_eccenerr1",
            "pl_eccenerr2",
            "st_spt",
        ]
    except:
        raise DataRetrievalFailure(
            "Couldn't obtain data from NEXSCI. Do you have an internet connection?"
        )
    df = pd.merge(
        left=planets,
        right=composite,
        how="left",
        left_on=["pl_hostname", "pl_letter"],
        right_on=["pl_hostname", "pl_letter"],
    )
    df = _fill_data(df)

    df["stripped_name"] = np.asarray(
        [n.lower().replace("-", "").replace(" ", "") for n in df.pl_hostname]
    )
    df[df.pl_tranflag == 1].to_csv(
        "{}/extensions/nexsci/data/planets.csv".format(PACKAGEDIR), index=False
    )


def _check_data_on_import():
    """Checks whether nexsci data is "fresh" on import.

    Data is considered out of date if a week has passed since downloading it.
    """
    fname = glob("{}/extensions/nexsci/data/planets.csv".format(PACKAGEDIR))
    if len(fname) == 0:
        _retrieve_online_data()
        fname = glob(
            "{}/extensions/nexsci/data/planets.csv".format(PACKAGEDIR)
        )
    st = os.stat(fname[0])
    mtime = st.st_mtime
    # If database is out of date, get it again.
    if datetime.datetime.now() - datetime.datetime.fromtimestamp(
        mtime
    ) > datetime.timedelta(days=7):
        log.warning("Database out of date. Redownloading...")
        _retrieve_online_data()


def _get_nexsci_data():
    """Returns pandas dataframe of all exoplanet data from nexsci
    """
    return pd.read_csv(
        "{}/extensions/nexsci/data/planets.csv".format(PACKAGEDIR)
    )


_check_data_on_import()