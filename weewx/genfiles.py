#
#    Copyright (c) 2009, 2010 Tom Keffer <tkeffer@gmail.com>
#
#    See the file LICENSE.txt for your full rights.
#
#    $Revision$
#    $Author$
#    $Date$
#
"""Generate files from templates.

This basically includes NOAA summary reports, and HTML files."""

import os.path
import syslog
import time

import Cheetah.Template
from Cheetah.Filters import Filter

import weewx.formatter
import weewx.station
import weewx.stats
import weewx.units
import weeutil.Almanac
import weeutil.weeutil

#===============================================================================
#                    Class GenFiles
#===============================================================================

class GenFiles(object):
    """Class for running files through templates"""
    
    def __init__(self, config_dict, skin_dict):
        """Initialize an instance of GenFiles.
        
        config_dict: weewx configuration dictionary with general station
        information.
        
        skin_dict: Skin configuration dictionary with selections specific
        to the presentation layer."""
        self.config_dict = config_dict
        self.skin_dict   = skin_dict
        self.outputted_dict = {}
        self.initStation()
        self.initStats()
        self.initUnits()

    def initStation(self):

        # station holds info such as 'altitude', 'latitude', etc. It seldom changes
        self.station = weewx.station.Station(self.config_dict, 
                                             self.skin_dict['Units']['Labels'],
                                             self.skin_dict['Units']['Groups'],
                                             self.skin_dict['Labels'].get('hemispheres', ('N','S','E','W')))
        
    def initStats(self):
        # Open up the stats database:
        statsFilename = os.path.join(self.config_dict['Station']['WEEWX_ROOT'], 
                                     self.config_dict['Stats']['stats_file'])
        self.statsdb = weewx.stats.StatsReadonlyDb(statsFilename,
                                                  float(self.config_dict['Station'].get('heating_base', '65')),
                                                  float(self.config_dict['Station'].get('cooling_base', '65')))
    
    def initUnits(self):
        self.unitTypeDict = weewx.units.getUnitTypeDict(self.skin_dict)
        
    def generateSummaryBy(self, by_time, start_ts, stop_ts):
        """This entry point is used for "SummaryBy" reports, such as NOAA monthly
        or yearly reports.
        
        by_time: Set to "SummaryByMonth" to run the template for each month between
        start_ts and stop_ts. Set to "SummaryByYear" for each year.
        
        start_ts: The first timestamp to be included.
        
        stop_ts: The last timestamp to be included.
        """
        
        if by_time == 'SummaryByMonth':
            _genfunc = weeutil.weeutil.genMonthSpans
        elif by_time == 'SummaryByYear':
            _genfunc = weeutil.weeutil.genYearSpans
        else:
            syslog.syslog(syslog.LOG_NOTICE, "genfiles: Unrecognized summary interval: %s. Skipped." % by_time)
            return

        self.outputted_dict[by_time] = []
        for subreport in self.skin_dict['FileGenerator'][by_time].sections:
    
            (template, destination_dir, encoding) = self._prepGen(self.skin_dict['FileGenerator'][by_time][subreport])

            ngen = 0
            t1 = time.time()

            # Loop through each timespan in the summary period
            for timespan in _genfunc(start_ts, stop_ts):

                # Get the start time as a timetuple.
                timespan_start_tt = time.localtime(timespan.start)
                #===============================================================
                # Calculate the output filename
                #===============================================================
                # Form the destination filename from the template name, replacing 'YYYY' with
                # the year, 'MM' with the month, and strip off the trailing '.tmpl':
                _yr_str = "%4d"  % timespan_start_tt[0]
                _filename = os.path.basename(template).replace('.tmpl','').replace('YYYY', _yr_str) 
                if by_time == 'SummaryByMonth' :
                    _mo_str = "%02d" % timespan_start_tt[1]
                    _filename = _filename.replace('MM', _mo_str)
                    # Save the included Year-Months so they can be used in an HTML drop down list:
                    self.outputted_dict['SummaryByMonth'].append("%s-%s" %(_yr_str, _mo_str))
                elif by_time == 'SummaryByYear' :
                    # Save the included years so they can be used in an HTML drop down list:
                    self.outputted_dict['SummaryByYear'].append(_yr_str)

                _fullpath = os.path.join(destination_dir, _filename)
    
                # If the file doesn't exist, or it is the last month, then
                # we must generate it
                if not os.path.exists(_fullpath) or timespan.includesArchiveTime(stop_ts):
    
                    searchList = self.getSummarySearchList(by_time, timespan)
                    # Run everything through the template engine
                    text = Cheetah.Template.Template(file       = template,
                                                     searchList = searchList + [{'encoding' : encoding}],
                                                     filter     = encoding,
                                                     filtersLib = weewx.genfiles)
                    # Open up the file that is to be created:
                    file = open(_fullpath, mode='w')
                    # Write it out
                    print >> file, text
                    # Close it
                    file.close()
                    ngen += 1
            
            t2 = time.time()
            elapsed_time = t2 - t1
            syslog.syslog(syslog.LOG_INFO, """genfiles: generated %d '%s' files in %.2f seconds""" % (ngen, by_time, elapsed_time))

    def generateToDate(self, currentRec, stop_ts):
        """This entry point is used for "To Date" reports, such as observations for
        this day, week, month, year, etc.
        
        currentRec: A dictionary containing current observation. Key is a type
        ('outTemp', 'barometer', etc.), value the value of the
        variable. Usually, this is an archive record.

        stop_ts: A timestamp. The HTML files generated will be current as of
        this time."""
        
        
        ngen = 0
        t1 = time.time()

        # Get an appropriate formatter:
        self.formatter =  weewx.formatter.Formatter(weewx.units.getStringFormatDict(self.skin_dict),
                                                    weewx.units.getHTMLLabelDict(self.skin_dict),
                                                    self.skin_dict['Labels']['Time'])

        self.initAlmanac(stop_ts)
    
        searchList = self.getToDateSearchList(currentRec, stop_ts)
            
        for subreport in self.skin_dict['FileGenerator']['ToDate'].sections:
    
            (template, destination_dir, encoding) = self._prepGen(self.skin_dict['FileGenerator']['ToDate'][subreport])
            
            # Form the destination filename:
            _filename = os.path.basename(template).replace('.tmpl','')
    
            #===================================================================
            # Here's where the heavy lifting occurs. Use Cheetah to actually
            # generate the files. It will use introspection on the searchList to
            # populate the parameters in the template file.
            # ===================================================================
            html = Cheetah.Template.Template(file       = template,
                                             searchList = searchList + [{'encoding' : encoding}],
                                             filter     = encoding,
                                             filtersLib = weewx.genfiles)

            file = open(os.path.join(destination_dir, _filename), mode='w')
            print >> file, html
            ngen += 1
        
        elapsed_time = time.time() - t1
        syslog.syslog(syslog.LOG_INFO, "genfiles: generated %d 'toDate' files in %.2f seconds" % (ngen, elapsed_time))
    
    def getSummarySearchList(self, by_time, timespan):
        """Return the searchList for the Cheetah Template engine for "summarize by" reports.
        
        Can easily be overridden to add things to the search list.
        """
        timespan_start_tt = time.localtime(timespan.start)
        (_yr, _mo) = timespan_start_tt[0:2]

        # Get the stats for this timespan from the database:
        stats = weewx.stats.TimespanStats(self.statsdb, timespan, self.unitTypeDict)
        
        search_dict = {'station'   : self.station,
                       'year_name' : _yr}
        
        if by_time == 'SummaryByMonth':
            search_dict['month'] = stats
            # Form a suitable name for the month:
            search_dict['month_name'] = time.strftime("%b", timespan_start_tt)
        elif by_time == 'SummaryByYear':
            search_dict['year'] = stats 
        
        return [search_dict]    

    def getToDateSearchList(self, currentRec, stop_ts):
        """Return the searchList for the Cheetah Template engine for "to date" generation.
        
        Can easily be overridden to add things to the search list.
        """

        # Calculate the time ranges for all the desired time spans.
        daySpan      = weeutil.weeutil.archiveDaySpan(stop_ts)
        weekSpan     = weeutil.weeutil.archiveWeekSpan(stop_ts, startOfWeek = self.station.week_start)
        monthSpan    = weeutil.weeutil.archiveMonthSpan(stop_ts)
        yearSpan     = weeutil.weeutil.archiveYearSpan(stop_ts)
        rainYearSpan = weeutil.weeutil.archiveRainYearSpan(stop_ts, self.station.rain_year_start)

        # Assemble the dictionary that will be given to the template engine:
        stats = {}
        stats['current']  = currentRec
        stats['day']      = weewx.stats.TimespanStats(self.statsdb, daySpan,      self.unitTypeDict)
        stats['week']     = weewx.stats.TimespanStats(self.statsdb, weekSpan,     self.unitTypeDict)
        stats['month']    = weewx.stats.TimespanStats(self.statsdb, monthSpan,    self.unitTypeDict)
        stats['year']     = weewx.stats.TimespanStats(self.statsdb, yearSpan,     self.unitTypeDict)
        stats['rainyear'] = weewx.stats.TimespanStats(self.statsdb, rainYearSpan, self.unitTypeDict)

        # Get a formatted view into the statistical information.
        statsFormatter = weewx.formatter.ModelFormatter(stats, self.formatter)
        
        searchList = [{'station'         : self.station,
                       'almanac'         : self.almanac},
                       self.outputted_dict,
                       statsFormatter]
        return searchList

    def initAlmanac(self, celestial_ts):
        """ Initialize an instance of weeutil.Almanac.Almanac for the station's
        lat and lon, and for a specific time.
        
        celestial_ts: The timestamp of the time for which the Almanac is to
        be initialized.
        """
        self.moonphases = self.skin_dict['Almanac'].get('moon_phases')

        # almanac holds celestial information (sunrise, phase of moon). Its celestial
        # data changes slowly.
        self.almanac = weeutil.Almanac.Almanac(celestial_ts, 
                                               self.station.latitude_f, 
                                               self.station.longitude_f, 
                                               self.moonphases)

    def _prepGen(self, subskin_dict):
        
        accum_dict = weeutil.weeutil.accumulateLeaves(subskin_dict)
        template = os.path.join(self.config_dict['Station']['WEEWX_ROOT'],
                                self.config_dict['Reports']['SKIN_ROOT'],
                                accum_dict['skin'],
                                accum_dict['template'])
        destination_dir = os.path.join(self.config_dict['Station']['WEEWX_ROOT'],
                                       accum_dict['HTML_ROOT'],
                                       os.path.dirname(accum_dict['template']))
        encoding = accum_dict['encoding']

        try:
            # Create the directory that is to receive the generated files.  If
            # it already exists an exception will be thrown, so be prepared to
            # catch it.
            os.makedirs(destination_dir)
        except OSError:
            pass

        return (template, destination_dir, encoding)
    

class html_entities(Filter):

    def filter(self, val, **kw):
        """Filter incoming strings so they use HTML entity characters"""
        if isinstance(val, unicode):
            filtered = val.encode('ascii', 'xmlcharrefreplace')
        elif val is None:
            filtered = ''
        elif isinstance(val, str):
            filtered = val.decode('utf-8').encode('ascii', 'xmlcharrefreplace')
        else:
            filtered = str(val)
        return filtered

class strict_ascii(Filter):

    def filter(self, val, **kw):
        """Filter incoming strings to strip out any non-ascii characters"""
        if isinstance(val, unicode):
            filtered = val.encode('ascii', 'ignore')
        elif val is None:
            filtered = ''
        elif isinstance(val, str):
            filtered = val.decode('utf-8').encode('ascii', 'ignore')
        else:
            filtered = str(val)
        return filtered

    
class utf8(Filter):

    def filter(self, val, **kw):
        """Filter incoming strings, converting to UTF-8"""
        if isinstance(val, unicode):
            filtered = val.encode('utf8')
        elif val is None:
            filtered = ''
        else:
            filtered = str(val)
        return filtered

