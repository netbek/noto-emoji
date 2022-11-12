const fs = require('fs-extra');
const globby = require('globby');
const path = require('path');
const {build, GLYPH, PNG, SVG} = require('punchcutter');

async function run() {
  await fs.remove('build');
  await fs.remove('temp');

  const files = await globby(['svg/emoji_*.svg']);

  await Promise.all(
    files.map(async (file) =>
      fs.readFile(file, 'utf-8').then((data) => {
        const destFile = path.join(
          'temp',
          path.basename(file).replace(/^emoji_(.+).svg$/, '$1.svg')
        );
        const destData = data.replace(
          /viewBox="0 0 128 128"/,
          'viewBox="0 0 128 128" width="128" height="128"'
        );
        return fs.outputFile(destFile, destData, 'utf-8');
      })
    )
  );

  await build({
    name: 'emoji',
    src: ['temp/*.svg'],
    builds: [
      {
        type: GLYPH,
        builds: [
          {type: SVG, dist: 'build/svg/'},
          {type: PNG, dist: 'build/png/mdpi/', scale: 20 / 128}
        ]
      }
    ]
  });
}

run();
