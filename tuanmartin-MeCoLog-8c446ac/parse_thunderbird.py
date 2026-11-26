import os

import Drain_large as Drain

input_dir = '/mnt/ntfs/martinez_code/logdata/'  # Input directory of log file
output_dir = '/mnt/ntfs/martinez_code/logdata/parse_result/'  # Output directory of parsing results
log_file = 'Thunderbird.log'  # Input log file name

# Set to False if your Thunderbird log does not include a leading label field.
has_label = True

if has_label:
    thunderbird_format = (
        '<Label> <Timestamp> <Date> <Node> <Month> <Day> <Time> '
        '<NodeRepeat> <Component>: <Content>'
    )
else:
    thunderbird_format = (
        '<Timestamp> <Date> <Node> <Month> <Day> <Time> '
        '<NodeRepeat> <Component>: <Content>'
    )

thunderbird_regex = [
    r'core\.\d+',
    r'(?:\/[\*\w\.-]+)+',  # path
    r'(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)(:|)',  # IP
    r'0x[0-9a-f]+(?: [0-9a-f]{8})*',  # hex
    r'[0-9a-f]{8}(?: [0-9a-f]{8})*',
    r'(?<=[^A-Za-z0-9])(\-?\+?\d+)(?=[^A-Za-z0-9])|[0-9]+$',  # Numbers
]

st = 0.5  # Similarity threshold
depth = 4  # Depth of all leaf nodes

os.makedirs(output_dir, exist_ok=True)
parser = Drain.LogParser(thunderbird_format, indir=input_dir,
                         outdir=output_dir, depth=depth, st=st, rex=thunderbird_regex)
parser.parse(log_file)
