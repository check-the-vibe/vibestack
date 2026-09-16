import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.machinery.SourceFileLoader('wallpaper',str(ROOT/'bin/vibestack-wallpaper'))
spec=importlib.util.spec_from_loader(loader.name,loader)
wallpaper=importlib.util.module_from_spec(spec)
loader.exec_module(wallpaper)

class WallpaperTests(unittest.TestCase):
    def test_metadata_excludes_credentials_queries_and_unknown_environment(self):
        info=wallpaper.metadata({'VIBESTACK_INSTANCE_NAME':'first-desktop','VIBESTACK_PUBLIC_URL':'https://host.example:11080/private?token=sentinel#secret','VIBESTACK_PUBLIC_PORT':'11080','SECRET':'sentinel'})
        self.assertEqual(info['origin'],'https://host.example:11080')
        self.assertEqual(info['ports']['WEB'],'11080')
        self.assertNotIn('sentinel',str(info))
        self.assertNotIn('private',info['origin'])
        info=wallpaper.metadata({'VIBESTACK_PUBLIC_URL':'https://user:sentinel@host.example:11080'})
        self.assertNotIn('sentinel',str(info))
        self.assertNotIn('user',info['origin'])

    def test_invalid_and_disabled_ports_are_not_advertised(self):
        info=wallpaper.metadata({'VIBESTACK_PUBLIC_PORT':'9'*10000,'VIBESTACK_SSH_PORT':'0','VIBESTACK_NATIVE_VNC_PORT':'70000'})
        self.assertEqual(set(info['ports'].values()),{'Not published'})

if __name__=='__main__': unittest.main()
