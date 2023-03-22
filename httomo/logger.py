import logging

#: set up logging to a user.log file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%d/%m/%Y %I:%M:%S %p',
    filename="user.log",
    filemode='w',
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)

#: set up an easy format for console use
formatter = logging.Formatter('%(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

user_logger = logging.getLogger(__file__)
user_logger.setLevel(logging.DEBUG)
