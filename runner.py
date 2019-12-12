from utils import get_url, initialize_monitoring
from log_analyzer import LogFileParser, LogFileCalculator, DrawMap

from config import RESULTS_PATH


def main():

    url = get_url()
    monitor = initialize_monitoring()

    log_parser = LogFileParser(url=url, monitor=monitor)
    parsed_log, postfix = log_parser.parse_log()

    log_calculator = LogFileCalculator(url=url, monitor=monitor, parsed_log=parsed_log)
    distance_report = log_calculator.run_calculation()
    distance_report.to_csv(RESULTS_PATH + '/' + f'distance_report_{postfix}.csv')

    drawer = DrawMap(monitor=monitor, parsed_log=parsed_log, postfix=postfix)
    drawer.draw_map()


if __name__ == "__main__":
    main()
