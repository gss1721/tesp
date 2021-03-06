#  Copyright (C) 2017 Battelle Memorial Institute
import json
import sys
import warnings
import csv
import fncs
from ppcasefile import ppcasefile
import numpy as np
import pypower.api as pp
#import scipy.io as spio
import math
import re
import copy
#import cProfile
#import pstats

def summarize_opf(res):
  bus = res['bus']
  gen = res['gen']

  Pload = bus[:,2].sum()
  Pgen = gen[:,1].sum()
  PctLoss = 100.0 * (Pgen - Pload) / Pgen

  print('success =', res['success'], 'in', res['et'], 'seconds')
  print('Total Gen =', Pgen, ' Load =', Pload, ' Loss =', PctLoss, '%')

  print('bus #, Pd, Qd, Vm, LMP_P, LMP_Q, MU_VMAX, MU_VMIN')
  for row in bus:
    print(int(row[0]),row[2],row[3],row[7],row[13],row[14],row[15],row[16])

  print('gen #, bus, Pg, Qg, MU_PMAX, MU_PMIN, MU_PMAX, MU_PMIN')
  idx = 1
  for row in gen:
    print(idx,int(row[0]),row[1],row[2],row[21],row[22],row[23],row[24])
    ++idx

def make_dictionary(ppc, rootname):
  fncsBuses = {}
  generators = {}
  unitsout = []
  branchesout = []
  bus = ppc['bus']
  gen = ppc['gen']
  cost = ppc['gencost']
  fncsBus = ppc['FNCS']
  units = ppc['UnitsOut']
  branches = ppc['BranchesOut']

  for i in range (gen.shape[0]):
    busnum = gen[i,0]
    bustype = bus[busnum-1,1]
    if bustype == 1:
      bustypename = 'pq'
    elif bustype == 2:
      bustypename = 'pv'
    elif bustype == 3:
      bustypename = 'swing'
    else:
      bustypename = 'unknown'
    generators[str(i+1)] = {'bus':int(busnum),'bustype':bustypename,'Pnom':float(gen[i,1]),'Pmax':float(gen[i,8]),'genfuel':'tbd','gentype':'tbd',
      'StartupCost':float(cost[i,1]),'ShutdownCost':float(cost[i,2]), 'c2':float(cost[i,4]), 'c1':float(cost[i,5]), 'c0':float(cost[i,6])}

  for i in range (fncsBus.shape[0]):
    busnum = int(fncsBus[i,0])
    busidx = busnum - 1
    fncsBuses[str(busnum)] = {'Pnom':float(bus[busidx,2]),'Qnom':float(bus[busidx,3]),'area':int(bus[busidx,6]),'zone':int(bus[busidx,10]),
      'ampFactor':float(fncsBus[i,2]),'GLDsubstations':[fncsBus[i,1]]}

  for i in range (units.shape[0]):
    unitsout.append ({'unit':int(units[i,0]),'tout':int(units[i,1]),'tin':int(units[i,2])})

  for i in range (branches.shape[0]):
    branchesout.append ({'branch':int(branches[i,0]),'tout':int(branches[i,1]),'tin':int(branches[i,2])})

  dp = open (rootname + "_m_dict.json", "w")
  ppdict = {'baseMVA':ppc['baseMVA'],'fncsBuses':fncsBuses,'generators':generators,'UnitsOut':unitsout,'BranchesOut':branchesout}
  print (json.dumps(ppdict), file=dp, flush=True)
  dp.close()

def parse_mva(arg):
  tok = arg.strip('+-; MWVAKdrij')
  vals = re.split(r'[\+-]+', tok)
  if len(vals) < 2: # only a real part provided
    vals.append('0')
  vals = [float(v) for v in vals]

  if '-' in tok:
    vals[1] *= -1.0
  if arg.startswith('-'):
    vals[0] *= -1.0

  if 'd' in arg:
    vals[1] *= (math.pi / 180.0)
    p = vals[0] * math.cos(vals[1])
    q = vals[0] * math.sin(vals[1])
  elif 'r' in arg:
    p = vals[0] * math.cos(vals[1])
    q = vals[0] * math.sin(vals[1])
  else:
    p = vals[0]
    q = vals[1]

  if 'KVA' in arg:
    p /= 1000.0
    q /= 1000.0
  elif 'MVA' in arg:
    p *= 1.0
    q *= 1.0
  else:  # VA
    p /= 1000000.0
    q /= 1000000.0

  return p, q

def main_loop():
  if len(sys.argv) == 2:
    rootname = sys.argv[1]
  else:
    print ('usage: python fncsPYPOWER.py rootname')
    sys.exit()

  ppc = ppcasefile()
  StartTime = ppc['StartTime']
  tmax = int(ppc['Tmax'])
  period = int(ppc['Period'])
  dt = int(ppc['dt'])
  make_dictionary(ppc, rootname)

  bus_mp = open ("bus_" + rootname + "_metrics.json", "w")
  gen_mp = open ("gen_" + rootname + "_metrics.json", "w")
  sys_mp = open ("sys_" + rootname + "_metrics.json", "w")
  bus_meta = {'LMP_P':{'units':'USD/kwh','index':0},'LMP_Q':{'units':'USD/kvarh','index':1},
    'PD':{'units':'MW','index':2},'QD':{'units':'MVAR','index':3},'Vang':{'units':'deg','index':4},
    'Vmag':{'units':'pu','index':5},'Vmax':{'units':'pu','index':6},'Vmin':{'units':'pu','index':7}}
  gen_meta = {'Pgen':{'units':'MW','index':0},'Qgen':{'units':'MVAR','index':1},'LMP_P':{'units':'USD/kwh','index':2}}
  sys_meta = {'Ploss':{'units':'MW','index':0},'Converged':{'units':'true/false','index':1}}
  bus_metrics = {'Metadata':bus_meta,'StartTime':StartTime}
  gen_metrics = {'Metadata':gen_meta,'StartTime':StartTime}
  sys_metrics = {'Metadata':sys_meta,'StartTime':StartTime}

  gencost = ppc['gencost']
  fncsBus = ppc['FNCS']
  ppopt = pp.ppoption(VERBOSE=0, OUT_ALL=0, PF_DC=1)
  loads = np.loadtxt('NonGLDLoad.txt', delimiter=',')

  for row in ppc['UnitsOut']:
    print ('unit  ', row[0], 'off from', row[1], 'to', row[2], flush=True)
  for row in ppc['BranchesOut']:
    print ('branch', row[0], 'out from', row[1], 'to', row[2], flush=True)

  nloads = loads.shape[0]
  ts = 0
  tnext_opf = -dt

  op = open (rootname + '.csv', 'w')
  print ('t[s],Converged,Pload,P7 (csv), GLD Unresp, P7 (opf), Resp (opf), GLD Pub, BID?, P7 Min, V7,LMP_P7,LMP_Q7,Pgen1,Pgen2,Pgen3,Pgen4,Pdisp, gencost2, gencost1, gencost0', file=op, flush=True)
  # print ('t[s], ppc-Pd5, ppc-Pd9, ppc-Pd7, bus-Pd7, ppc-Pg1, gen-Pg1, ppc-Pg2, gen-Pg2, ppc-Pg3, gen-Pg3, ppc-Pg4, gen-Pg4, ppc-Pg5, gen-Pg5, ppc-Cost2, gencost-Cost2, ppc-Cost1, gencost-Cost1, ppc-Cost0, gencost-Cost0', file=op, flush=True)
  fncs.initialize()

  # transactive load components
  csv_load = 0
  scaled_unresp = 0
  scaled_resp = 0
  resp_c0 = 0
  resp_c1 = 0
  resp_c2 = 0
  resp_max = 0
  gld_load = 0 # this is the actual
  # ==================================
  # Laurentiu Marinovici - 2017-12-14
  actual_load = 0
  new_bid = False
#  saveInd = 0
#  saveDataDict = {}
  # ===================================

  while ts <= tmax:
    if ts >= tnext_opf:  # expecting to solve opf one dt before the market clearing period ends, so GridLAB-D has time to use it
      idx = int ((ts + dt) / period) % nloads
      bus = ppc['bus']
      print('<<<<< ts = {}, ppc-Pd5 = {}, bus-Pd5 = {}, ppc-Pd7 = {}, bus-Pd7 = {}, ppc-Pd9 = {}, bus-Pd9 = {} >>>>>>>'.format(ts, ppc["bus"][4, 2], bus[4, 2], ppc["bus"][6, 2], bus[6, 2], ppc["bus"][8, 2], bus[8, 2]))
      gen = ppc['gen']
      branch = ppc['branch']
      gencost = ppc['gencost']
      csv_load = loads[idx,0]
      bus[4,2] = loads[idx,1]
      bus[8,2] = loads[idx,2]
      print('<<<<< ts = {}, ppc-Pd5 = {}, bus-Pd5 = {}, ppc-Pd7 = {}, bus-Pd7 = {}, ppc-Pd9 = {}, bus-Pd9 = {} >>>>>>>'.format(ts, ppc["bus"][4, 2], bus[4, 2], ppc["bus"][6, 2], bus[6, 2], ppc["bus"][8, 2], bus[8, 2]))
      # process the generator and branch outages
      for row in ppc['UnitsOut']:
        if ts >= row[1] and ts <= row[2]:
          gen[row[0],7] = 0
        else:
          gen[row[0],7] = 1
      for row in ppc['BranchesOut']:
        if ts >= row[1] and ts <= row[2]:
          branch[row[0],10] = 0
        else:
          branch[row[0],10] = 1
      bus[6,2] = csv_load
      # =================================
      # Laurentiu Marinovici - 2017-12-14
      # bus[6,2] = csv_load + actual_load
      # =================================
      for row in ppc['FNCS']:
        scaled_unresp = float(row[2]) * float(row[3])
        newidx = int(row[0]) - 1
        bus[newidx,2] += scaled_unresp
      print('<<<<< ts = {}, ppc-Pd5 = {}, bus-Pd5 = {}, ppc-Pd7 = {}, bus-Pd7 = {}, ppc-Pd9 = {}, bus-Pd9 = {} >>>>>>>'.format(ts, ppc["bus"][4, 2], bus[4, 2], ppc["bus"][6, 2], bus[6, 2], ppc["bus"][8, 2], bus[8, 2]))
      gen[4][9] = -resp_max * float(fncsBus[0][2])
      gencost[4][3] = 3
      gencost[4][4] = resp_c2
      gencost[4][5] = resp_c1
      gencost[4][6] = resp_c0

      # =================================
      # Laurentiu Marinovici - 2017-12-14
      # print('Before running OPF:')
      # print('Disp load/neg gen: Pg = ', gen[4][1], ', Pmax = ', gen[4][8], ', Pmin = ', gen[4][9], ', status = ', gen[4][7])
      # print('Disp load/neg gen cost coefficients: ', gencost[4][4], ', ', gencost[4][5], ', ', gencost[4][6])
      
      # gen[4, 7] = 1 # turn on dispatchable load
      #ppc['gen'] = gen
      #ppc['bus'] = bus
      #ppc['branch'] = branch
      #ppc['gencost'] = gencost
      # print (ts, ppc["bus"][4, 2], ppc["bus"][8, 2], ppc["bus"][6, 2], bus[6, 2], ppc["gen"][0, 1], gen[0, 1], ppc["gen"][1, 1], gen[1, 1], ppc["gen"][2, 1], gen[2, 1], ppc["gen"][3, 1], gen[3, 1], ppc["gen"][4, 1], gen[4, 1], ppc["gencost"][4, 4], gencost[4, 4], ppc["gencost"][4, 5], gencost[4, 5], ppc["gencost"][4, 6], gencost[4, 6], sep=',', file=op, flush=True)
      # =====================================================================================================================

      res = pp.runopf(ppc, ppopt)
      
      # =================================
      # Laurentiu Marinovici - 2017-12-21
#      mpcKey = 'mpc' + str(saveInd)
#      resKey = 'res' + str(saveInd)
#      saveDataDict[mpcKey] = copy.deepcopy(ppc)
#      saveDataDict[resKey] = copy.deepcopy(res)
#      saveInd += 1
      # =================================      

      bus = res['bus']
      gen = res['gen']
      Pload = bus[:,2].sum()
      Pgen = gen[:,1].sum()
      Ploss = Pgen - Pload
      scaled_resp = -1.0 * gen[4,1]
      # CSV file output
      print (ts, res['success'], 
             '{:.3f}'.format(bus[:,2].sum()), 
             '{:.3f}'.format(csv_load), 
             '{:.3f}'.format(scaled_unresp), 
             '{:.3f}'.format(bus[6,2]), 
             '{:.3f}'.format(scaled_resp), 
             '{:.3f}'.format(actual_load), 
             new_bid, 
             '{:.3f}'.format(gen[4,9]), 
             '{:.3f}'.format(bus[6,7]), 
             '{:.3f}'.format(bus[6,13]), 
             '{:.3f}'.format(bus[6,14]), 
             '{:.2f}'.format(gen[0,1]), 
             '{:.2f}'.format(gen[1,1]), 
             '{:.2f}'.format(gen[2,1]), 
             '{:.2f}'.format(gen[3,1]), 
             '{:.2f}'.format(res['gen'][4, 1]), 
             '{:.6f}'.format(ppc['gencost'][4, 4]), 
             '{:.4f}'.format(ppc['gencost'][4, 5]), 
             '{:.4f}'.format(ppc['gencost'][4, 6]), 
             sep=',', file=op, flush=True)
      fncs.publish('LMP_B7', 0.001 * bus[6,13])
      fncs.publish('three_phase_voltage_B7', 1000.0 * bus[6,7] * bus[6,9])
      print('**OPF', ts, csv_load, scaled_unresp, gen[4][9], scaled_resp, bus[6,2], 'LMP', 0.001 * bus[6,13])
      # update the metrics
      sys_metrics[str(ts)] = {rootname:[Ploss,res['success']]}
      bus_metrics[str(ts)] = {}
      for i in range (fncsBus.shape[0]):
        busnum = int(fncsBus[i,0])
        busidx = busnum - 1
        row = bus[busidx].tolist()
        bus_metrics[str(ts)][str(busnum)] = [row[13]*0.001,row[14]*0.001,row[2],row[3],row[8],row[7],row[11],row[12]]
      gen_metrics[str(ts)] = {}
      for i in range (gen.shape[0]):
        row = gen[i].tolist()
        busidx = int(row[0] - 1)
        gen_metrics[str(ts)][str(i+1)] = [row[1],row[2],float(bus[busidx,13])*0.001]
      tnext_opf += period
      if tnext_opf > tmax:
        print ('breaking out at',tnext_opf,flush=True)
        break
    # apart from the OPF, keep loads updated
    ts = fncs.time_request(ts + dt)
    events = fncs.get_events()
    new_bid = False
    for key in events:
      topic = key.decode()
      # ==================================
      # Laurentiu Marinovici - 2017-12-14l
      # print('The event is: ........ ', key)
      # print('The topic is: ........ ', topic)
      # print('The value is: ........ ', fncs.get_value(key).decode())
      # =============================================================
      if topic == 'UNRESPONSIVE_KW':
        unresp_load = 0.001 * float(fncs.get_value(key).decode())
        fncsBus[0][3] = unresp_load # poke unresponsive estimate into the bus load slot
        new_bid = True
      elif topic == 'RESPONSIVE_MAX_KW':
        resp_max = 0.001 * float(fncs.get_value(key).decode()) # in MW
        new_bid = True
      elif topic == 'RESPONSIVE_M':
        # resp_c2 = 1000.0 * 0.5 * float(fncs.get_value(key).decode())
        resp_c2 = -1e6 * float(fncs.get_value(key).decode())
        new_bid = True
      elif topic == 'RESPONSIVE_B':
        # resp_c1 = 1000.0 * float(fncs.get_value(key).decode())
        resp_c1 = 1e3 * float(fncs.get_value(key).decode())
        new_bid = True
      # ============================================
      # Laurentiu Marinovici
      elif topic == 'RESPONSIVE_BB':
        resp_c0 = -float(fncs.get_value(key).decode())
        new_bid = True
      # ============================================
      elif topic == 'UNRESPONSIVE_PRICE': # not actually used
        unresp_price = float(fncs.get_value(key).decode())
        new_bid = True
      else:
        gld_load = parse_mva (fncs.get_value(key).decode()) # actual value, may not match unresp + resp load
        # ==================================
        # Laurentiu Marinovici - 2017-12-14
        # print('GLD real = ', float(gld_load[0]), '; GLD imag = ', float(gld_load[1]))
        # print('Amp factor = ', float(fncsBus[0][2]))
        # ==================================================================
        actual_load = float(gld_load[0]) * float(fncsBus[0][2])
        print('  Time = ', ts, '; actual load real = ', actual_load)
    if new_bid == True:
      print('**Bid', ts, unresp_load, resp_max, resp_c2, resp_c1, resp_c0)

  # Laurentiu Marinovici - 2017-12-21
#  spio.savemat('matFile.mat', saveDataDict)
  # ===================================
  print ('writing metrics', flush=True)
  print (json.dumps(bus_metrics), file=bus_mp, flush=True)
  print (json.dumps(gen_metrics), file=gen_mp, flush=True)
  print (json.dumps(sys_metrics), file=sys_mp, flush=True)
  print ('closing files', flush=True)
  bus_mp.close()
  gen_mp.close()
  sys_mp.close()
  op.close()
  print ('finalizing FNCS', flush=True)
  fncs.finalize()

main_loop()

#with warnings.catch_warnings():
#  warnings.simplefilter("ignore") # TODO - pypower is using NumPy doubles for integer indices

#  profiler = cProfile.Profile ()
#  profiler.runcall (main_loop)
#  stats = pstats.Stats(profiler)
#  stats.strip_dirs()
#  stats.sort_stats('cumulative')
#  stats.print_stats()
