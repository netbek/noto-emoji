const fs = require('fs-extra');
const globby = require('globby');
const path = require('path');
const Promise = require('bluebird');
const {build, GLYPH, PNG, SVG} = require('punchcutter');

fs.remove('build')
  .then(() => fs.remove('temp'))
  .then(() => globby(['svg/emoji_*.svg']))
  .then(files =>
    Promise.mapSeries(files, inputFile =>
      fs.readFile(inputFile, 'utf-8').then(inputData => {
        const outputFile = path.join(
          'temp',
          path.basename(inputFile).replace(/^emoji_(.+).svg$/, '$1.svg')
        );
        const outputData = inputData.replace(
          /viewBox="0 0 128 128"/,
          'viewBox="0 0 128 128" width="128" height="128"'
        );
        return fs.outputFile(outputFile, outputData, 'utf-8');
      })
    )
  )
  .then(() => {
    build({
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
  });
