const test=require('node:test');
const assert=require('node:assert/strict');
const {parseSheetPaste}=require('../../static/js/lead-sheets.js');
test('Excel clipboard includes rows, empty cells and a trailing line ending',()=>assert.deepEqual(parseSheetPaste('Acme\t\t00123\r\nBeta\tSam\t04567\r\n'),[['Acme','','00123'],['Beta','Sam','04567']]));
test('quoted cells retain embedded tabs, lines and escaped quotation marks',()=>assert.deepEqual(parseSheetPaste('"A\tB"\t"Notes\nTwo lines"\n"He said ""hello"""\tC'),[['A\tB','Notes\nTwo lines'],['He said "hello"','C']]));
test('literal quotations within a business name are retained',()=>assert.deepEqual(parseSheetPaste('Jo"s Cafe\tDining'),[['Jo"s Cafe','Dining']]));
test('trailing blank columns remain aligned',()=>assert.deepEqual(parseSheetPaste('A\t\t\nB\t\t'),[['A','',''],['B','','']]));
