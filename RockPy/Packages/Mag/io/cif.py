import RockPy
import RockPy.core.ftype
from RockPy.tools.pandas_tools import XYZ2DIM, DIM2XYZ, correct_dec_inc
from datetime import datetime
import pandas as pd
import numpy as np
import os
import time
from RockPy.core.utils import correction


class Cif(RockPy.core.ftype.Ftype):
    datacolumns = ['mtype', 'level', 'geo_dec', 'geo_inc', 'strat_dec', 'strat_inc', 'intensity', 'ang_err',
                   'plate_dec', 'plate_inc', 'std_x', 'std_y', 'std_z', 'user', 'date', 'time']

    corrections = {"TW": [0, 0],
                   "TN": [90, 0],
                   "TE": [180, 0],  #
                   "TS": [270, 0],
                   "ET": [0, 90],
                   "ST": [90, 90],
                   "WT": [180, 90],
                   "NT": [270, 90],
                   "BE": [0, 180],  #
                   "BS": [90, 180],
                   "BW": [180, 180],
                   "BN": [270, 180],
                   ####
                   "WB": [0, 270],
                   "NB": [90, 270],
                   "EB": [180, 270],
                   "WS": [270, 270],
                   }

    def __init__(self, dfile, snames=None, reload=False, mdata=None, **kwargs):
        super().__init__(dfile, snames=snames, dialect=None, reload=reload, mdata=mdata, **kwargs)

        self.data = self.add_missing_levels(self.data)
        self.data['level'] /= 10  # mT
        self.data['level'] /= 1000  # T

    @classmethod
    def add_missing_levels(cls, data):
        """
        Adds the correct level for a UAFX measurement, assuming it is the same level as the AF measurement before

        Returns
        -------
            pandas Dataframe with a corrected levels column
        """
        data = data.copy()

        AF_index = [(i, v) for i, v in enumerate(data['mtype']) if v == 'AF']

        old_levels = data['level'].values

        # just in case make a copy of the old levels for reference
        data['old_levels'] = old_levels

        new_levels = old_levels
        for idx, level in enumerate(new_levels):
            # if 'ARM'  in data['mtype'].iloc[idx]:
            #     level = 0
            if 'UAFX' in data['mtype'].iloc[idx]:
                prev_AF_idx = max(i for i, v in AF_index if i < idx)
                level = data['level'].iloc[prev_AF_idx]
            new_levels[idx] = level
        data.loc[:, 'level'] = new_levels
        return data

    def read_file(self):
        """
        The sample format is illustrated by the following fragment:
        00000000011111111112222222222333333333344444444445555555555666666666677777777778
        12345678901234567890123456789012345678901234567890123456789012345678901234567890
        erb  1.0A    Sample just above tuff
          113.0 291.0  63.0  43.0  46.0   1.0
        NRM     41.2  49.7  91.4  41.0 3.44E-05   5.5 184.1 -13.1  0.0289  0.0270  0.0468
        TT 150  46.7  41.3  84.3  33.7 1.79E-05   7.5 189.4 -20.9  0.0188  0.0130  0.0228
        TT 225  55.6  36.8  84.5  25.5 1.44E-05   4.0 197.8 -23.3  0.0193  0.0252  0.0171

        It starts with the header rows. See read_header

        The following lines are in the order the demagnetizations were carried out. The first 2 characters (3 for NRM
        only) is the demag type (AF for alternating field, TT for thermal, CH for chemical, etc.), the next 4 (3 for
        NRM) is the demag level (°C for thermal, mT for alternating field, etc.), the next 6 (first blank for all the
        following fields) for geographic ("in situ") declination of the sample's magnetic vector, next 6 for geographic
        inclination, next 6 for stratigraphic declination, next 6 for stratigraphic inclination, next 9 for normalized
        intensity (emu/cm^3; multiply by the core volume/mass to get the actual measured core intensity), next 6 for
        measurement error angle, next 6 for core plate declination, next 6 for core plate inclination, and the final
        three fields of 8 each are the standard deviations of the measurement in the core's x, y, and z coordinates
        in 10^5 emu. NB in 2003, it appears the CIT format is actually using three final fields of 9 characters, not 8.

        Presently only the sample id line, the second line, and the first ten fields (to core inclination but
        excepting the error angle) of the demag lines are used in PaleoMag. Except for the stratigraphic level,
        info on the second line is only displayed in the info window or used in the "Headers..." command. A possibility
        exists that future versions will plot Zijder plots with the measurement uncertainties.

        Returns
        -------
            pd.DataFrame
        """

        with open(self.dfile) as f:
            raw_data = f.readlines()

        rows, raw_header_rows = self.separate_row(raw_data)

        self.header = self.read_header(raw_header_rows)

        data = pd.DataFrame(
            columns=['mtype', 'level', 'geo_dec', 'geo_inc', 'strat_dec', 'strat_inc', 'intensity', 'ang_err',
                     'plate_dec', 'plate_inc', 'std_x', 'std_y', 'std_z', 'user', 'date', 'time'], data=rows)

        # moment is stored in 10^-5 emu -> 1E-5 * 1E-3 -> Am^2
        data['intensity'] *= 1e5
        data.loc[:, ['std_x', 'std_y', 'std_z', 'intensity']] *= 1e-3

        data = DIM2XYZ(data, colD='plate_dec', colI='plate_inc', colM='intensity')
        data.loc[:, 'datetime'] = pd.to_datetime(data['date'] + ' ' + data['time'])
        data = data.set_index('datetime')
        return data

    @classmethod
    def read_UP_file(cls, dfile, sample_id, reload=False):
        if not dfile in cls.imported_files or reload:
            with open(dfile) as raw_data:
                raw_data = raw_data.readlines()

            header = raw_data[0]
            raw_data = [n.rstrip().replace(',', '|') for n in raw_data]

            # in case of weird double <CR> symbols
            raw_data = [i for i in raw_data if i]
            raw_data = [n.split('|') for n in raw_data]

            header = header.rstrip().replace(',', '|')
            header = header.split('|')
            header.append('datetime')
            raw_data = [[n[0], n[1], int(n[2]), n[3], int(n[4]), int(n[5]), float(n[6]), float(n[7]), float(n[8]),
                         pd.to_datetime(n[9])] for n in raw_data[1:]]
            cls.imported_files[dfile] = pd.DataFrame(columns=header, data=raw_data)

        out = cls.imported_files[dfile].copy()

        if not sample_id in set(out['Sample']):
            RockPy.log.error('Could not find sample_id << {} >> in file << {} >.! '
                             'Please check correct spelling'.format(sample_id, os.path.basename(dfile)))
            return

        sdata = out.loc[out.Sample == sample_id].copy()

        # convert from emu to Am^2
        sdata.loc[:,['X', 'Y', 'Z']] *= 1e-3

        sdata = sdata.rename(columns={"X": "X_", "Y": "Y_", "Z": "Z_"})
        sdata.loc[:,'z'] = sdata['Z_']

        # rotate measurements into sample coordinates
        for idx, v in sdata.iterrows():
            x, y = v[['X_', 'Y_']].values

            if v['MsmtNum'] == 1:
                sdata.loc[idx, 'x'] = x
                sdata.loc[idx, 'y'] = y
            elif v['MsmtNum'] == 2:
                sdata.loc[idx, 'x'] = y
                sdata.loc[idx, 'y'] = -x
            elif v['MsmtNum'] == 3:
                sdata.loc[idx, 'x'] = -x
                sdata.loc[idx, 'y'] = -y
            elif v['MsmtNum'] == 4:
                sdata.loc[idx, 'x'] = -y
                sdata.loc[idx, 'y'] = x

            sdata.loc[idx, 'y'] *= -1

            if v['Direction'] == 'D':
                sdata.loc[idx, 'y'] *= -1
                sdata.loc[idx, 'z'] *= -1

        sdata = XYZ2DIM(sdata, colX='x', colY='y', colZ='z', colD='D', colI='I', colM='M')

        sdata = sdata.set_index('datetime')
        dfile = os.path.basename(dfile)
        sdata.loc[:, 'dfile'] = dfile

        mtype = ''.join([n for n in dfile.split('.')[0] if not n.isnumeric()]).rstrip()
        level = ''.join([n for n in dfile.split('.')[0] if n.isnumeric() if n])

        if 'UAFX' in mtype:
            mtype += level[0]
            level = level[1:]
        if mtype == 'NRM':
            level = 0

        sdata.loc[:, 'mtype'] = mtype
        sdata.loc[:, 'level'] = int(level)
        return sdata

    @staticmethod
    def separate_row(raw_data):
        rows = []
        header_rows = []
        for idx, row in enumerate(raw_data):
            if row.startswith('#'):
                continue
            # data rows start at idx 2
            if idx > 1:
                # index of first number
                num_index = min(i for i, v in enumerate(row) if v.isnumeric())

                # shift index for direction to be displayed in mtype
                if row.startswith('UAFX'):
                    num_index += 1

                mtype = row[:num_index].rstrip()

                if row.startswith('NRM'):
                    level = 0
                else:
                    level = int(row[num_index:6])

                # other columns are separate by whitespace -> split(' ')
                values = [i for i in row[6:].split(' ') if i]

                # set string variables
                user, date, time = values[11:14]

                # set float variables
                geo_dec, geo_inc, strat_dec, strat_inc, intensity, ang_err, plate_dec, plate_inc, std_x, std_y, std_z = np.array(
                    values[:11]).astype(float)
                # intensity *= 1e-5
                rows.append(
                    [mtype, level, geo_dec, geo_inc, strat_dec, strat_inc, intensity, ang_err, plate_dec, plate_inc,
                     std_x, std_y, std_z, user, date, time])
            else:
                header_rows.append(row.rstrip())
        return rows, header_rows

    @classmethod
    def read_header(self, header_rows):
        """
        In the first line the first four characters are the locality id, the next 9 the sample id, and the remainder
        (to 255) is a sample comment.

        In the second line, the first character is ignored, the next 6 comprise the stratigraphic level
        (usually in meters). The remaining fields are all the same format: first character ignored (should be a blank
        space) and then 5 characters used. These are the core strike, core dip, bedding strike, bedding dip, and core
        volume or mass. Conventions are discussed below. CIT format can include fold axis and plunge, which at present
        is unused.

        Parameters
        ----------
        header_rows

        Returns
        -------

        """
        locality = header_rows[0][:4].strip(' ')
        sample_id = header_rows[0][4:13].strip(' ')

        widths = [(1, 7), (8, 13), (14, 19), (20, 25), (26, 31), (32, 37)]
        labels = ['stratigraphic_level', 'core_strike', 'core_dip', 'bedding_strike', 'bedding_dip',
                  'core_volume_or_mass']
        lw_dict = dict(zip(labels, widths))

        header = pd.DataFrame(index=[sample_id])
        header['locality_id'] = locality
        for label in lw_dict:
            v = header_rows[1][lw_dict[label][0]:lw_dict[label][1]].strip(' ')

            if v:
                header.loc[sample_id, label] = float(v)
            else:
                header.loc[sample_id, label] = None
        header.index.name = 'sample_id'
        return header

    @classmethod
    def from_rapid(cls, files_or_folder,
                   sample_id, locality_id='',
                   core_strike=0., core_dip=0.,
                   bedding_strike=0., bedding_dip=0.,
                   core_volume_or_mass=1,
                   stratigraphic_level='', comment='', user='lancaster',
                   reload=False):
        """
        reads Up/DOWN files or folder containing these and creates a cif-like object

        Parameters
        ----------
        files_or_folder

        Returns
        -------

        """

        if os.path.isdir(files_or_folder):
            files = [os.path.join(files_or_folder, f) for f in os.listdir(files_or_folder)]
        else:
            files = RockPy.to_tuple(files_or_folder)

        files = sorted([f for f in files if (f.endswith('UP') or f.endswith('DOWN'))])

        # read all the files , create list of Dataframes
        raw_df = []
        for i, dfile in enumerate(files):
            # print('reading file << {:>20} >> {:>4} of {:>4}'.format(os.path.basename(dfile), i, len(files)), end='\r')
            readdf = cls.read_UP_file(dfile, sample_id, reload=reload)

            if readdf is not None:
                raw_df.append(readdf)

        average_df = []
        for i, df in enumerate(raw_df):
            # print('averaging file {:>4} of {:>4}'.format(i, len(raw_df)), end='\r')
            average_df.append(cls.return_mean_from_UP_file(df))
        if len(average_df) > 1:
            data = pd.concat(average_df)
        else:
            data = average_df[0]

        data = XYZ2DIM(data, colX='x', colY='y', colZ='z', colI='plate_inc', colD='plate_dec', colM='intensity')

        data = data.sort_index()
        data.index.name = 'datetime'

        data.loc[:,'user'] = user[:8]
        data.loc[:,'date'] = data.index.strftime('%Y-%m-%d')
        data.loc[:,'time'] = data.index.strftime('%H:%M:%S')

        data.loc[:,'core_dip'] = core_dip
        data.loc[:,'core_strike'] = core_strike
        data.loc[:,'bedding_dip'] = bedding_dip
        data.loc[:,'bedding_strike'] = bedding_strike

        data = cls._correct_core(data, core_dip, core_strike)

        data = cls._correct_strat(data, bedding_dip, bedding_strike)

        header_lines = cls.write_header(bedding_dip=bedding_dip, bedding_strike=bedding_strike,
                                        core_dip=core_dip, core_strike=core_strike,
                                        sample_id=sample_id, locality_id=locality_id,
                                        core_volume_or_mass=core_volume_or_mass,
                                        stratigraphic_level=stratigraphic_level, comment=comment)
        header = cls.read_header(header_rows=header_lines)
        return cls(dfile='from .UP files', mdata=data, header=header)
    
    """ properties """
    @property
    def geo_dim(self):
        return self.data[['geo_dec','geo_inc','intensity']]
    @property
    def plate_dim(self):
        return self.data[['plate_dec','plate_inc','intensity']]
    @property
    def plate_xyz(self):
        return self.data[['x','y','z']]\
    @property
    def geo_xyz(self):
        return DIM2XYZ(self.geo_dim, colD='geo_dec', colI='geo_inc',colM='intensity')
    
    def mean_levels(self):
        """
        Calculates the average for (AF, UAFX1, UAFX2, ...) of the same level and recalcuates the plate, core and strat
        declination and inclinations.

        Notes
        -----
        `_mean_levels' can be used for testing purposes. This does not reset self.data with the means but returns a
        copy of the Dataframe.

        Returns
        -------
            self.data
        """
        core_dip = self.header['core_dip']
        core_strike = self.header['core_strike']
        strat_dip = self.header['bedding_dip']
        strat_strike = self.header['bedding_strike']

        self.data = self._mean_levels(self.data,
                                      core_dip=core_dip, core_strike=core_strike,
                                      strat_dip=strat_dip, strat_strike=strat_strike)
        return self.data

    @classmethod
    def _mean_levels(self, df, core_dip, core_strike, strat_dip, strat_strike):
        """
        Calculates the average for (AF, UAFX1, UAFX2, ...) of the same level and recalcuates the plate, core and strat
        declination and inclinations.

        Notes
        -----
        Is called by `mean_levels' resets self.data with the means.

        Returns
        -------
        pd.DataFrame
            averaged data
        """
        df = df.copy()
        index_name = df.index.name
        # make sure the index is datetime
        df = df.reset_index()
        df = df.set_index('level')

        # make sure the data is sorted
        df = df.sort_values('datetime')

        out = df.loc[~np.in1d(df['mtype'], ['UAFX1', 'UAFX2', 'UAFX3'])].copy()
        mean = df.groupby('level').mean()

        out.loc[:, 'x'] = mean.loc[:, 'x']
        out.loc[:, 'y'] = mean.loc[:, 'y']
        out.loc[:, 'z'] = mean.loc[:, 'z']

        out = self._recalc_plate(out)
        out = self._correct_core(out, core_dip, core_strike)
        out = self._correct_strat(out, strat_dip, strat_strike)

        # reset df to initial index
        out = out.reset_index()
        out = out.set_index(index_name)

        return out

    def reset_plate(self):
        self.data = self._recalc_plate(self.data)

    @classmethod
    def _recalc_plate(cls, df):
        df = XYZ2DIM(df, colX='x', colY='y', colZ='z', colI='plate_inc', colD='plate_dec', colM='intensity')
        return df

    def reset_geo(self, dip=None, strike=None):

        if dip is None:
            dip = self.header['core_dip']
        if strike is None:
            strike = self.header['core_strike']

        self.data = self._correct_core(self.data, dip, strike)
        self.header['core_dip'] = dip
        self.header['core_strike'] = strike

    @classmethod
    def _correct_core(cls, df, dip, strike):
        """
        Wrapper function callinr RockPy
        Parameters
        ----------
        df
        dip
        strike

        Returns
        -------
            pandas.DataFrame
        """
        cls.log().info(f'Correcting data for core dip ({dip}) and strike ({strike})')

        return correct_dec_inc(df=df, dip=dip, strike=(strike - 90),
                               colI='plate_inc', colD='plate_dec',
                               newD='geo_dec', newI='geo_inc')

    def reset_strat(self, dip=None, strike=None):
        """
        Recalculates the data in stratigraphic direction. Sets self.data
        Parameters
        ----------
        dip float
            dip of strat
        strike float
            strike of strat
        """

        if dip is None:
            dip = self.header['strat_dip']
        if strike is None:
            strike = self.header['strat_strike']

        self.data = self._correct_strat(self.data, dip, strike)

    @classmethod
    def _correct_strat(cls, df, dip, strike):
        """
        Wrapper function callinr RockPy
        Parameters
        ----------
        df
        dip
        strike

        Returns
        -------
            pandas.DataFrame
        """
        cls.log().warning(
            f'Correcting data for stratigraphic dip ({dip}) and strike ({strike}).\n THIS HAS NOT BEEN TESTED!')

        return correct_dec_inc(df=df, dip=dip, strike=strike,
                               colI='geo_inc', colD='geo_dec',
                               newI='strat_inc', newD='strat_dec')

    def correct_wrong_direction(self):
        self.data = self._correct_wrong_direction(df=self.data,
                                                  core_dip=self.header['core_dip'][0],
                                                  core_strike=self.header['core_strike'][0],
                                                  bedding_dip=self.header['bedding_dip'][0],
                                                  bedding_strike=self.header['bedding_strike'][0])

    @classmethod
    def _correct_wrong_direction(cls, df, core_dip, core_strike, bedding_dip, bedding_strike, **kwargs):
        """
        corrects the measurement, in case the up/down measurement directions were wrongly chosen.

        Returns
        -------

        """
        df = df.copy()

        df['z'] *= -1
        df['y'] *= -1

        df = cls._recalc_plate(df)
        df = cls._correct_core(df=df, dip=core_dip, strike=core_strike)
        df = cls._correct_strat(df=df, dip=bedding_dip, strike=bedding_strike)

        return df

    @staticmethod
    def return_mean_from_UP_file(df):
        """
        takes a DataFrame created from reading in an (UP?DOWN) file (see. read_UP_files) and returns a new dataframe
        where the average XYZ values of the holder was subtracted and the XYZ components have been averaged.
        Parameters
        ----------
        df

        Returns
        -------

        """
        means = {'S': None, 'H': None, 'Z': None}
        stdevs = {'S': None, 'H': None, 'Z': None}

        for mtype in ('S', 'H'):
            d = df[df['MsmtType'] == mtype]

            mean = d.groupby(d.index).mean()
            std = d.groupby(d.index).std()

            means[mtype] = mean
            stdevs[mtype] = std

        out = pd.DataFrame(
            columns=['mtype', 'level', 'geo_dec', 'geo_inc', 'strat_dec', 'strat_inc', 'intensity', 'ang_err',
                     'plate_dec', 'plate_inc', 'std_x', 'std_y', 'std_z', 'user', 'date', 'time', 'sample',
                     'direction'],
            index=sorted(set(df.index)))

        # out['mtype'] = df.iloc[0]['mtype']
        out['direction'] = df.iloc[0]['Direction']

        out['level'] = df.iloc[0]['level']
        out['sample'] = df.iloc[0]['Sample']
        out['mtype'] = df.iloc[0]['mtype']
        out['mtype'] = df.iloc[0]['mtype']
        # add standard deviations to df
        out['std_x'] = stdevs['S']['x']
        out['std_y'] = stdevs['S']['y']
        out['std_z'] = stdevs['S']['z']

        # calculate Dec/Inc standard deviations # todo calculate this properly i.e. alpha 95 or something
        out['ang_err'] = stdevs['S']['D']

        out[['x', 'y', 'z']] = Cif.correct_holder(means['S'][['x', 'y', 'z']], means['H'][['x', 'y', 'z']])
        return out

    @staticmethod
    def correct_holder(sample_means, holder_means):
        # subtract holder measurement
        corrected = sample_means - holder_means
        return corrected

    def export(self, fname, sample_id=None, **kwargs):
        """
        Exports a cif file from the data
        Parameters
        ----------
        fname str
            where the data should be stored
        sample_id: name of the sample for the cif file
        """

        header = self.header.reset_index().iloc[0].to_dict()
        header.update(kwargs)
        if sample_id is not None:
            header['sample_id'] = sample_id

        data = self.data.copy()

        data = data.reset_index()

        with open(fname, 'w+') as f:
            header = self.write_header(**header)
            f.writelines(header)
            for row in data.iterrows():
                row = self.write_cif_line(row)
                f.write(row + '\n')

    @classmethod
    def write_header(cls, core_strike, core_dip,
                     bedding_strike, bedding_dip,
                     sample_id,
                     core_volume_or_mass=1, locality_id='', stratigraphic_level='', comment=''):
        """
        Returns a list of strings with the correct Cit formatting. Line 1 = locality and sample info,
        line 2 = orientation info

        Parameters
        ----------
        bedding_dip
        bedding_strike
        core_dip
        core_strike
        sample_id
        core_volume_or_mass
        locality_id
        stratigraphic_level
        comment

        Returns
        -------

        """
        if np.isnan(stratigraphic_level):
            stratigraphic_level = ''
        comment += f' >> RockPy exported {datetime.now().strftime("%Y-%m-%d %H:%M")}'

        out = ['{:<4}{:<9}{}\n'.format(locality_id, sample_id, comment[:255]),
               ' {:>6} {:>5} {:>5} {:>5} {:>5} {:>5}\n'.format(stratigraphic_level, core_strike, core_dip,
                                                               bedding_strike, bedding_dip, core_volume_or_mass),
               ]
        return out

    @staticmethod
    def write_cif_line(series):
        """
        Writes one cit foramatted line

        Parameters
        ----------
        series: pd.Series
            The line, as a pandas Series from the data Dataframe.

        Returns
        -------
        str
            string formatted to cit format
        """

        series = series[1].copy()
        level = int(series['level'] * 10000)
        series[['std_x', 'std_y', 'std_z', 'intensity']] *= 1e3  # to emu
        series[['intensity']] *= 1e-5  # std is saved in 10^-5 emu

        mtype = series['mtype']

        timedate = pd.to_datetime(series['date'] + ' ' + series['time'])

        columns = ['geo_dec', 'geo_inc', 'strat_dec', 'strat_inc', 'intensity', 'ang_err',
                   'plate_dec', 'plate_inc', 'std_x', 'std_y', 'std_z', 'user']
        formats = {'mtype': '{:<2}', 'level': '{:>4}',
                   'geo_dec': '{:>5.1f}', 'geo_inc': '{:>5.1f}', 'strat_dec': '{:>5.1f}', 'strat_inc': '{:>5.1f}',
                   'intensity': '{:.2E}', 'ang_err': '{:05.1f}', 'plate_dec': '{:>5.1f}', 'plate_inc': '{:>5.1f}',
                   'std_x': '{:>.6f}', 'std_y': '{:>.6f}', 'std_z': '{:>.6f}',
                   'user': '{:>7}', 'date': '{:>4}', 'time': '{:>4}'}

        if mtype == 'NRM' or mtype == 'ARM':
            formats['mtype'] = "{:<3}"
            formats['level'] = '{:>3}'
            level = ''

        if "UAFX" in mtype:
            formats['mtype'] = "{:<5}"
            formats['level'] = '{:>1}'
            level = str(level)[-1]

        start = ''.join([formats['mtype'].format(mtype), formats['level'].format(level), ' '])
        rest = ' '.join(formats[fmt].format(series[fmt]) for fmt in columns)
        date = timedate.strftime(' %Y-%m-%d')
        time = timedate.strftime(' %H:%M:%S')

        return start + rest + date + time + ' '


if __name__ == '__main__':
    from RockPy.tools.pandas_tools import DIM2XYZ

    NRM_MIL14 = Cif('/Users/mike/Dropbox/science/harvard/2G_data/mike/MIL/NRM/MIL13', reload=True)
    # print(NRM_MIL14.data[['x', 'y', 'z']].iloc[0])
    # print(DIM2XYZ(NRM_MIL14.data[['geo_dec', 'geo_inc', 'intensity']], colD='geo_dec', colI='geo_inc',
    #               colM='intensity').iloc[0])
    # NRM_MIL14.reset_geo(dip=90, strike=90)
    # print(DIM2XYZ(NRM_MIL14.data[['geo_dec', 'geo_inc', 'intensity']], colD='geo_dec', colI='geo_inc',
    #               colM='intensity').iloc[0])
