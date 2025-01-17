import argparse
import datetime
import subprocess
import os

def main(args):
    path = args.input
    if path.endswith('/'):
        path = path[:-1]
    if os.path.isdir(path):
        basename = os.path.basename(path)
        dirname = os.path.dirname(path)
        os.system('cd {dirname} && tar -zcf {basename}.tgz {basename}'.format(dirname=dirname,
                                                                                  basename=basename))
        result = subprocess.run(['md5', '-q', '{}.tgz'.format(path)], stdout=subprocess.PIPE)
        md5hash = result.stdout.decode('utf-8').strip()
        ctime = os.path.getctime('{path}.tgz'.format(path=path))
        ctimestamp = datetime.datetime.fromtimestamp(ctime).__str__()
        ctimestamp = ctimestamp.replace('-', '').replace(' ', '').replace(':', '')
        ctimestamp = ctimestamp[0:12]
        os.system('mv {path}.tgz {path}_{ctimestamp}_{md5hash}.tgz'.format(path=path,
                                                                                   ctimestamp=ctimestamp,
                                                                                   md5hash=md5hash))
        print('--package written to {path}_{ctimestamp}_{md5hash}.tgz'.format(path=path,
                                                                                      ctimestamp=ctimestamp,
                                                                                      md5hash=md5hash))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Package a directory.")
    parser.add_argument('input', type=str, help='Directory to be packaged')
    args = parser.parse_args()
    main(args)
