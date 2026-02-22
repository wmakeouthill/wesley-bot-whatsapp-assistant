var fs = require('fs');
var c = fs.readFileSync('/evolution/dist/main.js', 'utf8');
var i = c.indexOf('Baileys version env');
if (i < 0) { console.log('NOT FOUND'); process.exit(1); }
console.log('=== BEFORE ===');
console.log(c.substring(i-600, i));
console.log('=== AFTER ===');
console.log(c.substring(i, i+600));
