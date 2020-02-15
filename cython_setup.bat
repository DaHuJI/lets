@ECHO OFF
title Cythonizing files...
cythonize -a -i common/db/dbConnector.pyx
cythonize -a -i handlers/getScoreHandler.pyx
cythonize -a -i handlers/submitModularHandler.pyx
cythonize -a -i objects/beatmap.pyx
cythonize -a -i objects/score.pyx
cythonize -a -i objects/scoreboard.pyx
cythonize -a -i objects/scoreboardRelax.pyx
cythonize -a -i objects/scoreRelax.pyx
cythonize -a -i pp/catch_the_pp/ppCalc.pyx
cythonize -a -i pp/catch_the_pp/constants.pyx
cythonize -a -i pp/catch_the_pp/osu/ctb/difficulty.pyx
cythonize -a -i pp/catch_the_pp/osu_parser/beatmap.pyx
cythonize -a -i pp/catch_the_pp/osu_parser/curves.pyx
cythonize -a -i pp/catch_the_pp/osu_parser/hitobject.pyx
cythonize -a -i pp/catch_the_pp/osu_parser/mathhelper.pyx
echo.
echo Cythonized all files.
pause