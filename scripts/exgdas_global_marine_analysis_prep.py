#!/usr/bin/env python3
################################################################################
#  UNIX Script Documentation Block
#                      .                                             .
# Script name:         exufsda_global_marine_analysis_prep.py
# Script description:  Stages files and generates YAML for UFS Global Marine Analysis
#
# Author: Guillaume Vernieres      Org: NCEP/EMC     Date: 2022-03-28
#
# Abstract: This script stages the marine observations, backgrounds and prepares
#           the variational yaml necessary to produce a UFS Global Marine Analysis.
#
# $Id$
#
# Attributes:
#   Language: Python3
#
################################################################################

# import os and sys to add ush to path
import os
import sys
import yaml
import glob
import dateutil.parser as dparser
import f90nml
import shutil
import logging
import subprocess
from datetime import datetime, timedelta

# set up logger
logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO, datefmt='%Y-%m-%d %H:%M:%S')

# get absolute path of ush/ directory either from env or relative to this file
my_dir = os.path.dirname(__file__)
my_home = os.path.dirname(os.path.dirname(my_dir))
gdas_home = os.path.join(os.getenv('HOMEgfs'), 'sorc', 'gdas.cd')
sys.path.append(os.path.join(os.getenv('HOMEgfs', my_home), 'ush'))
print(f"sys.path={sys.path}")


# import UFSDA utilities
import ufsda


def gen_bkg_list(window_begin=' ', bkg_path='.', file_type='gdas.t*.ocnf00[4-9]', yaml_name='bkg.yaml'):
    """
    Generate a YAML of the list of backgrounds for the pseudo model
    """
    files = glob.glob(bkg_path+'/*'+file_type+'*')
    files.sort()

    # Fix missing value in diag files
    for v in ['Temp', 'Salt', 'ave_ssh', 'h', 'MLD']:
        for att in ["_FillValue", "missing_value"]:
            fix_diag_ch_jobs = []  # change att value
            fix_diag_d_jobs = []   # delete att
            for bkg in files:
                fix_diag_ch_jobs.append('ncatted -h -a '+att+','+v+',o,d,9999.0 '+bkg)
                fix_diag_d_jobs.append('ncatted -h -a '+att+','+v+',d,d,1.0 '+bkg)

            for c in fix_diag_ch_jobs:
                logging.info(f"{c}")
                os.system(c)
                result = subprocess.run(c, stdout=subprocess.PIPE, shell=True)
                result.stdout.decode('utf-8')

            for c in fix_diag_d_jobs:
                logging.info(f"{c}")
                os.system(c)
                result = subprocess.run(c, stdout=subprocess.PIPE, shell=True)
                result.stdout.decode('utf-8')

    # Create yaml of list of backgrounds
    bkg_list = []
    bkg_date = window_begin + timedelta(hours=1)
    for bkg in files:
        # TODO (G): DANGER!!! There is no error trap in soca to assert that the date
        #           of the background is consistent with the date in the yaml.
        #           Check here?
        ocn_filename = os.path.splitext(os.path.basename(bkg))[0]+'.nc'
        bkg_dict = {'date': bkg_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'basename': bkg_path+'/',
                    'ocn_filename': ocn_filename,
                    'read_from_file': 1}
        bkg_date = bkg_date + timedelta(hours=1)
        bkg_list.append(bkg_dict)
    dict = {'states': bkg_list}
    f = open(yaml_name, 'w')
    yaml.dump(dict, f, sort_keys=False, default_flow_style=False)

################################################################################
# runtime environment variables, create directories


logging.info(f"---------------- Setup runtime environement")

comout = os.getenv('COMOUT')
comin_obs = os.getenv('COMIN_OBS')
staticsoca_dir = os.getenv('SOCA_INPUT_FIX_DIR')

# create analysis directory for files
anl_dir = os.path.join(comout, 'analysis')
ufsda.mkdir(anl_dir)

# create output directory for obs
diags = os.path.join(comout, 'analysis', 'diags')
ufsda.mkdir(diags)

# create output directory for soca DA
ufsda.mkdir(os.path.join(comout, 'analysis', 'Data'))


################################################################################
# fetch observations

logging.info(f"---------------- Stage observations")

# setup the archive, local and shared R2D2 databases
ufsda.r2d2.setup(r2d2_config_yaml='r2d2_config.yaml', shared_root=comin_obs)

# create config dict from runtime env
envconfig = ufsda.misc_utils.get_env_config(component='notatm')
os.environ['OBS_DATE'] = envconfig['OBS_DATE']
os.environ['OBS_DIR'] = envconfig['OBS_DIR']
os.environ['OBS_PREFIX'] = envconfig['OBS_PREFIX']
os.environ['DIAG_DIR'] = diags
stage_cfg = ufsda.parse_config(templateyaml=os.path.join(gdas_home,
                                                         'parm',
                                                         'templates',
                                                         'stage.yaml'), clean=True)

# stage observations from R2D2 to COMIN_OBS and then link to analysis subdir
ufsda.stage.obs(stage_cfg)

################################################################################
# stage backgrounds from COMIN_GES to analysis subdir
logging.info(f"---------------- Stage backgrounds")

stage_cfg['background_dir'] = os.getenv('COMIN_GES')
ufsda.stage.background(stage_cfg)

################################################################################
# stage static files
logging.info(f"---------------- Stage static files")
ufsda.stage.soca_fix(stage_cfg)

################################################################################
# prepare JEDI yamls
logging.info(f"---------------- Generate JEDI yaml files")

# get list of DA variables
soca_vars = os.environ.get("SOCA_VARS").split(",")

# link yaml for grid generation
gridgen_yaml = os.path.join(gdas_home,
                            'parm',
                            'soca',
                            'gridgen',
                            'gridgen.yaml')
ufsda.disk_utils.symlink(gridgen_yaml,
                         os.path.join(stage_cfg['stage_dir'], 'gridgen.yaml'))

# generate YAML file for parametric diag of B
berr_yaml = os.path.join(anl_dir, 'parametric_stddev_b.yaml')
berr_yaml_template = os.path.join(gdas_home,
                                  'parm',
                                  'soca',
                                  'berror',
                                  'parametric_stddev_b.yaml')
config = {}
ufsda.yamltools.genYAML(config, output=berr_yaml, template=berr_yaml_template)

# link yaml for decorrelation length scales
corscales_yaml = os.path.join(gdas_home,
                              'parm',
                              'soca',
                              'berror',
                              'soca_setcorscales.yaml')
ufsda.disk_utils.symlink(corscales_yaml,
                         os.path.join(stage_cfg['stage_dir'], 'soca_setcorscales.yaml'))

# generate yaml for bump C
# TODO (Guillaume): move the possible vars somewhere else
vars3d = ['tocn', 'socn', 'uocn', 'vocn', 'chl', 'biop']
vars2d = ['ssh', 'cicen', 'hicen', 'hsnon', 'swh',
          'sw', 'lw', 'lw_rad', 'lhf', 'shf', 'us']

# TODO (Guillaume): do something with soca_vars.
vars = ['ssh', 'tocn', 'socn']
logging.info(f"over-writting {soca_vars} with {vars}")
for v in vars:
    if v in vars2d:
        dim = '2d'
    else:
        dim = '3d'
    bumpC_yaml = os.path.join(anl_dir, 'soca_bump'+dim+'_C_'+v+'.yaml')
    bumpC_yaml_template = os.path.join(gdas_home,
                                       'parm',
                                       'soca',
                                       'berror',
                                       'soca_bump_C_split.yaml')
    bumpdir = 'bump'+dim+'_'+v
    ufsda.disk_utils.mkdir(os.path.join(anl_dir, bumpdir))
    config = {'datadir': bumpdir}
    os.environ['CVAR'] = v
    ufsda.yamltools.genYAML(config, output=bumpC_yaml, template=bumpC_yaml_template)

# generate yaml for soca_var
var_yaml = os.path.join(anl_dir, 'var.yaml')
var_yaml_template = os.path.join(gdas_home,
                                 'parm',
                                 'soca',
                                 'variational',
                                 '3dvarfgat.yaml')
half_assim_freq = timedelta(hours=int(os.getenv('assim_freq'))/2)
window_begin = datetime.strptime(os.getenv('CDATE'), '%Y%m%d%H') - half_assim_freq
gen_bkg_list(window_begin=window_begin, bkg_path=os.getenv('COMIN_GES'), yaml_name='bkg_list.yaml')
soca_ninner = os.getenv('SOCA_NINNER')
config = {
    'OBS_DATE': os.getenv('PDY')+os.getenv('cyc'),
    'BKG_LIST': 'bkg_list.yaml',
    'COVARIANCE_MODEL': 'SABER',
    'NINNER': soca_ninner,
    'SABER_BLOCKS_YAML': os.path.join(gdas_home, 'parm', 'soca', 'berror', 'saber_blocks.yaml')}
logging.info(f"{config}")
ufsda.yamltools.genYAML(config, output=var_yaml, template=var_yaml_template)

# link of convenience
# TODO (G): The last restart dumped by MOM6 at the end of the forecast does not
#           include a date in the file name (MOM.res.nc) but intermittent restarts do.
#           What's below will probably never work, and/or rarely/never
#           point to the correct background at the start of the window.
#           Since we are doing FGAT, MOM.res.nc should point to the restart at the begining
#           of the DA window.
# TODO (G): Check for consistency between MOM.res.nc at t=0 and the diag files read by the
#           pseudo model. Is the vertical geometry the same? Do we care if it isn't?
# TODO (G): We should be able to use a diag file in the "background" definition in var.yaml
#           instead of a restart but we end up with NaN's after going through the "linear model".
#           Check why ...
bkg_rst = 'MOM.res.'+window_begin.strftime('%Y-%m-%d-%H-%M-%S')+'.nc'
ufsda.disk_utils.symlink(os.path.join(stage_cfg['background_dir'], 'RESTART', bkg_rst),
                         os.path.join(comout, 'analysis', 'INPUT', 'MOM.res.nc'))
# TODO (G): Doing what's below should alaways work, but currently segfaulting ...
# diag_ic = os.path.join(os.getenv('COMIN_GES'), 'gdas.t12z.ocnf003.nc')
# ufsda.disk_utils.symlink(diag_ic,
#                         os.path.join(comout, 'analysis', 'INPUT', 'MOM.res.nc'))

# prepare input.nml
mom_input_nml_src = os.path.join(gdas_home, 'parm', 'soca', 'fms', 'input.nml')
mom_input_nml_tmpl = os.path.join(stage_cfg['stage_dir'], 'mom_input.nml.tmpl')
mom_input_nml = os.path.join(stage_cfg['stage_dir'], 'mom_input.nml')
ufsda.disk_utils.copyfile(mom_input_nml_src, mom_input_nml_tmpl)
domain_stack_size = os.getenv('DOMAIN_STACK_SIZE')

ymdhms = [int(s) for s in window_begin.strftime('%Y,%m,%d,%H,%M,%S').split(',')]
with open(mom_input_nml_tmpl, 'r') as nml_file:
    nml = f90nml.read(nml_file)
    nml['ocean_solo_nml']['date_init'] = ymdhms
    nml['fms_nml']['domains_stack_size'] = int(domain_stack_size)
    ufsda.disk_utils.removefile(mom_input_nml)
    nml.write(mom_input_nml)
