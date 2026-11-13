# AWR report extract: awr_23ai_free.html

## Summary

- DB name: FREE
- Instance: FREE
- Release: 23.26.3.0.0
- Begin snapshot id: 4
- End snapshot id: 5
- Begin snapshot time: 12-Nov-26 04:08:12
- End snapshot time: 12-Nov-26 04:08:13
- Elapsed: 0.02 (mins)
- DB time: 0.02 (mins)

## load_profile: Load Profile

| Load Profile | Per Second | Per Transaction | Per Exec | Per Call |
|---|---|---|---|---|
| DB Time(s): | 1.0 | 0.1 | 0.00 | 0.02 |
| DB CPU(s): | 0.8 | 0.0 | 0.00 | 0.02 |
| Background CPU(s): | 0.0 | 0.0 | 0.00 | 0.00 |
| Redo size (bytes): | 7,746,311.8 | 407,456.0 |  |  |
| Logical read (blocks): | 30,231.9 | 1,590.2 |  |  |
| Block changes: | 11,026.6 | 580.0 |  |  |
| Physical read (blocks): | 560.8 | 29.5 |  |  |
| Physical write (blocks): | 578.0 | 30.4 |  |  |
| Read IO requests: | 33.3 | 1.8 |  |  |
| Write IO requests: | 16.2 | 0.9 |  |  |
| Read IO (MB): | 4.4 | 0.2 |  |  |
| Write IO (MB): | 4.5 | 0.2 |  |  |
| IM scan rows: | 0.0 | 0.0 |  |  |
| Session Logical Read IM: | 0.0 | 0.0 |  |  |
| User calls: | 46.6 | 2.5 |  |  |
| Parses (SQL): | 1,699.6 | 89.4 |  |  |
| Hard parses (SQL): | 127.4 | 6.7 |  |  |
| SQL Work Area (MB): | 30.5 | 1.6 |  |  |
| Logons: | 0.0 | 0.0 |  |  |
| User logons: | 0.0 | 0.0 |  |  |

3 more rows dropped (--max-rows 20).

## top_events: Top 10 Foreground Events by Total Wait Time

| Event | Waits | Total Wait Time (sec) | Avg Wait | % DB time | Wait Class |
|---|---|---|---|---|---|
| DB CPU |  | .9 |  | 88.1 |  |
| log file switch completion | 1 | .1 | 103.95ms | 10.3 | Configuration |
| direct path sync | 1 | 0 | 5.18ms | .5 | User I/O |
| direct path write | 17 | 0 | 292.18us | .5 | User I/O |
| log file switch (checkpoint incomplete) | 1 | 0 | 3.09ms | .3 | Configuration |
| latch: In memory undo latch | 1 | 0 | 2.17ms | .2 | Concurrency |
| db file sequential read | 13 | 0 | 95.69us | .1 | User I/O |
| db file scattered read | 26 | 0 | 46.54us | .1 | User I/O |
| log file sync | 4 | 0 | 245.50us | .1 | Commit |
| control file sequential read | 87 | 0 | 4.26us | .0 | System I/O |

## time_model: Time Model Statistics

| Statistic Name | Time (s) | % of DB Time | % of Total CPU Time |
|---|---|---|---|
| sql execute elapsed time [1] | 1.00 | 99.14 |  |
| DB CPU | 0.89 | 88.12 | 100.00 |
| parse time elapsed [1] | 0.17 | 16.60 |  |
| hard parse elapsed time [1] | 0.15 | 15.26 |  |
| PL/SQL execution elapsed time [1] | 0.04 | 3.62 |  |
| hard parse (sharing criteria) elapsed time [1] | 0.01 | 0.58 |  |
| repeated bind elapsed time [1] | 0.00 | 0.03 |  |
| DB time | 1.01 |  |  |
| total CPU time | 0.89 |  |  |

## sql_by_elapsed: SQL ordered by Elapsed Time

| Elapsed Time (s) | Executions | Elapsed Time per Exec (s) | %Total | %CPU | %IO | SQL Id | SQL Module | PDB Name | SQL Text |
|---|---|---|---|---|---|---|---|---|---|
| 0.85 | 1 | 0.85 | 84.39 | 99.13 | 0.45 | 0ya0su0v21g20 | pack-tools |  | select /* LLM in use is pack-t... |
| 0.38 | 1 | 0.38 | 38.00 | 99.99 | 0.00 | 2pkpuk0vd342z |  |  | insert into wrh$_mvparameter (... |
| 0.13 | 1 | 0.13 | 13.42 | 16.92 | 5.78 | 1b85hgs1u7wgd | pack-tools |  | create /* LLM in use is pack-t... |
| 0.04 | 1 | 0.04 | 3.87 | 86.89 | 3.08 | bxu1s25bf60rv |  |  | begin prvt_hdm.execute_manual_... |
| 0.01 | 1 | 0.01 | 0.91 | 99.87 | 0.00 | 9nuwrm2gww27b |  |  | insert into wrh$_parameter (db... |
| 0.01 | 1 | 0.01 | 0.91 | 110.40 | 0.00 | 04vd3ua81u3kg |  |  | insert into wrh$_memory_resize... |
| 0.01 | 1 | 0.01 | 0.89 | 93.13 | 14.13 | apsf3whganf28 | pack-tools |  | select /* LLM in use is pack-t... |
| 0.01 | 1 | 0.01 | 0.55 | 107.51 | 0.00 | 855yvjgw89nfy |  |  | insert into WRH$_SYSSTAT (dbid... |
| 0.00 | 1 | 0.00 | 0.48 | 89.46 | 0.00 | 5rpac32ur336y | pack-tools |  | select /* LLM in use is pack-t... |
| 0.00 | 1 | 0.00 | 0.43 | 96.68 | 0.00 | 975713susc49j |  |  | SELECT UPPER(NVL(MAX(VALUE), '... |

## sql_by_cpu: SQL ordered by CPU Time

| CPU Time (s) | Executions | CPU per Exec (s) | %Total | Elapsed Time (s) | %CPU | %IO | SQL Id | SQL Module | PDB Name | SQL Text |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.84 | 1 | 0.84 | 94.94 | 0.85 | 99.13 | 0.45 | 0ya0su0v21g20 | pack-tools |  | select /* LLM in use is pack-t... |
| 0.38 | 1 | 0.38 | 43.12 | 0.38 | 99.99 | 0.00 | 2pkpuk0vd342z |  |  | insert into wrh$_mvparameter (... |
| 0.03 | 1 | 0.03 | 3.81 | 0.04 | 86.89 | 3.08 | bxu1s25bf60rv |  |  | begin prvt_hdm.execute_manual_... |
| 0.02 | 1 | 0.02 | 2.58 | 0.13 | 16.92 | 5.78 | 1b85hgs1u7wgd | pack-tools |  | create /* LLM in use is pack-t... |
| 0.01 | 1 | 0.01 | 1.14 | 0.01 | 110.40 | 0.00 | 04vd3ua81u3kg |  |  | insert into wrh$_memory_resize... |
| 0.01 | 1 | 0.01 | 1.03 | 0.01 | 99.87 | 0.00 | 9nuwrm2gww27b |  |  | insert into wrh$_parameter (db... |
| 0.01 | 1 | 0.01 | 0.94 | 0.01 | 93.13 | 14.13 | apsf3whganf28 | pack-tools |  | select /* LLM in use is pack-t... |
| 0.01 | 1 | 0.01 | 0.67 | 0.01 | 107.51 | 0.00 | 855yvjgw89nfy |  |  | insert into WRH$_SYSSTAT (dbid... |
| 0.00 | 1 | 0.00 | 0.49 | 0.00 | 89.46 | 0.00 | 5rpac32ur336y | pack-tools |  | select /* LLM in use is pack-t... |
| 0.00 | 1 | 0.00 | 0.48 | 0.00 | 96.68 | 0.00 | 975713susc49j |  |  | SELECT UPPER(NVL(MAX(VALUE), '... |

## sql_by_gets: SQL ordered by Gets

| Buffer Gets | Executions | Gets per Exec | %Total | Elapsed Time (s) | %CPU | %IO | SQL Id | SQL Module | PDB Name | SQL Text |
|---|---|---|---|---|---|---|---|---|---|---|
| 36,028 | 1 | 36,028.00 | 113.28 | 0.85 | 99.1 | .5 | 0ya0su0v21g20 | pack-tools |  | select /* LLM in use is pack-t... |
| 5,779 | 1 | 5,779.00 | 18.17 | 0.01 | 107.5 | 0 | 855yvjgw89nfy |  |  | insert into WRH$_SYSSTAT (dbid... |
| 3,446 | 1 | 3,446.00 | 10.84 | 0.04 | 86.9 | 3.1 | bxu1s25bf60rv |  |  | begin prvt_hdm.execute_manual_... |
| 2,819 | 1 | 2,819.00 | 8.86 | 0.00 | 81.6 | 0 | 1zb651a37ccgg |  |  | insert into wrh$_latch (dbid, ... |
| 2,285 | 1 | 2,285.00 | 7.18 | 0.00 | 48.3 | 0 | 18c2yb5aj919t |  |  | SELECT nvl(e1, 0) as e1, nvl(... |
| 978 | 1 | 978.00 | 3.08 | 0.13 | 16.9 | 5.8 | 1b85hgs1u7wgd | pack-tools |  | create /* LLM in use is pack-t... |
| 772 | 1 | 772.00 | 2.43 | 0.00 | 86.6 | 0 | 6s13b9tky9gv9 |  |  | SELECT snap_id, per_pdb , TS#,... |
| 678 | 1 | 678.00 | 2.13 | 0.01 | 93.1 | 14.1 | apsf3whganf28 | pack-tools |  | select /* LLM in use is pack-t... |
| 668 | 1 | 668.00 | 2.10 | 0.00 | 89.5 | 0 | 5rpac32ur336y | pack-tools |  | select /* LLM in use is pack-t... |
| 574 | 1 | 574.00 | 1.80 | 0.01 | 99.9 | 0 | 9nuwrm2gww27b |  |  | insert into wrh$_parameter (db... |
| 495 | 1 | 495.00 | 1.56 | 0.00 | 129.4 | 0 | 2vxuj0u0rdgug |  |  | UPDATE wrh$_seg_stat_obj ob S... |
| 397 | 93 | 4.27 | 1.25 | 0.00 | 98.6 | 0 | 05d0ckrja68sf |  |  | insert into wrm$_snapshot_deta... |
| 319 | 1 | 319.00 | 1.00 | 0.00 | 75.8 | 0 | agw6jz8y9t6qr |  |  | insert into WRH$_EVENT_HISTOGR... |

## sql_by_reads: SQL ordered by Reads

| Physical Reads | Executions | Reads per Exec | %Total | Elapsed Time (s) | %CPU | %IO | SQL Id | SQL Module | PDB Name | SQL Text |
|---|---|---|---|---|---|---|---|---|---|---|
| 589 | 1 | 589.00 | 99.83 | 0.01 | 93.13 | 14.13 | apsf3whganf28 | pack-tools |  | select /* LLM in use is pack-t... |
| 464 | 1 | 464.00 | 78.64 | 0.00 | 79.97 | 21.64 | djxtkb4gbn2f5 |  |  | SELECT /* OPT_DYN_SAMP */ /*+ ... |
| 1 | 1 | 1.00 | 0.17 | 0.85 | 99.13 | 0.45 | 0ya0su0v21g20 | pack-tools |  | select /* LLM in use is pack-t... |
| 1 | 1 | 1.00 | 0.17 | 0.04 | 86.89 | 3.08 | bxu1s25bf60rv |  |  | begin prvt_hdm.execute_manual_... |
| 1 | 1 | 1.00 | 0.17 | 0.00 | 18.26 | 59.24 | ft1ww2u1k6w07 |  |  | INSERT INTO SYS.wri$_adv_tasks... |
| 0 | 1 | 0.00 | 0.00 | 0.01 | 110.40 | 0.00 | 04vd3ua81u3kg |  |  | insert into wrh$_memory_resize... |
| 0 | 93 | 0.00 | 0.00 | 0.00 | 98.62 | 0.00 | 05d0ckrja68sf |  |  | insert into wrm$_snapshot_deta... |
| 0 | 3 | 0.00 | 0.00 | 0.00 | 98.91 | 0.00 | 062savj8zgzut |  |  | UPDATE sys.wri$_adv_parameters... |
| 0 | 4 | 0.00 | 0.00 | 0.00 | 67.10 | 0.00 | 0dqdmhh7xjbwp | SQLcl-MCP |  | BEGIN DBMS_APPLICATION_INFO.S... |
| 0 | 1 | 0.00 | 0.00 | 0.00 | 93.85 | 0.00 | 0f15mx3sq1x2s |  |  | SELECT /* OPT_DYN_SAMP */ /*+ ... |

## segments_by_logical_reads: Segments by Logical Reads

| Owner | Tablespace Name | Object Name | Subobject Name | Obj. Type | Obj# | Dataobj# | Logical Reads | %Total | PDB Name |
|---|---|---|---|---|---|---|---|---|---|
| SYS | SYSAUX | WRH$_SYSSTAT_PK | WRH$_SYSSTAT_3638231841_MXSN | INDEX PARTITION | 72872 | 72872 | 5,184 | 16.30 |  |
| SYS | SYSAUX | WRH$_LATCH_PK | WRH$_LATCH_3638231841_MXSN | INDEX PARTITION | 72800 | 72800 | 2,512 | 7.90 |  |
| SYS | SYSAUX | WRH$_EVENT_NAME |  | TABLE | 14652 | 14652 | 2,272 | 7.14 |  |
| SYSTEM | SYSTEM | AWR_FIXTURE_LOAD |  | TABLE | 73293 | 73293 | 2,016 | 6.34 |  |
| SYS | SYSAUX | WRH$_SEG_STAT_OBJ | WRH$_SEG_STAT_OBJ_3638231841_MXSN | TABLE PARTITION | 72893 | 72893 | 864 | 2.72 |  |

## segments_by_physical_reads: Segments by Physical Reads

| Owner | Tablespace Name | Object Name | Subobject Name | Obj. Type | Obj# | Dataobj# | Physical Reads | %Total | PDB Name |
|---|---|---|---|---|---|---|---|---|---|
| SYSTEM | SYSTEM | AWR_FIXTURE_LOAD |  | TABLE | 73293 | 73293 | 583 | 98.81 |  |

## init_params: Parameters modified by this container

| Parameter Name | Begin value | End value (if different) | PDB Name |
|---|---|---|---|
| common_user_prefix |  |  |  |
| fast_start_parallel_rollback | FALSE |  |  |
| sga_target | 0 |  |  |
| spatial_vector_acceleration | FALSE |  |  |
| undo_tablespace | UNDOTBS1 |  |  |

## Sections not found

- instance_efficiency
