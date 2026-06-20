const vm = require('vm');
const fs = require('fs');
const code = fs.readFileSync('resume-website/script.js','utf8');

const ctx = {
    console, setTimeout,
    localStorage: { getItem(){ return null; }, setItem(){}, removeItem(){} },
    window: {},
    document: {
        createElement(){ return {style:{},appendChild(){},innerHTML:'',textContent:'',className:'',setAttribute(){}}; },
        body:{ insertAdjacentHTML(){}, appendChild(){} },
        documentElement:{ style:{ setProperty(){} } },
        getElementById(){ return null; },
        head:{ appendChild(){} },
        querySelector(){ return null; },
        querySelectorAll(){ return []; },
        title: ''
    },
    location: { href: 'file:///test.html' },
    html2pdf: undefined,
    alert: function(){},
    confirm: function(){ return true; },
    prompt: function(){ return null; },
    Event: function(){},
    CustomEvent: function(){},
    Image: function(){}
};
vm.createContext(ctx);

try {
    vm.runInContext(code, ctx);
    console.log('RUN OK');
    console.log('window.openTemplateLibrary:', typeof ctx.window.openTemplateLibrary);
    console.log('window.openResumeEditor:', typeof ctx.window.openResumeEditor);
    console.log('window.generatePDF:', typeof ctx.window.generatePDF);
} catch(e) {
    console.log('RUN ERROR:', e.message);
    console.log(e.stack);
}

// Now test initAll inside the context
try {
    const testCode = 'try { console.log("initAll type:", typeof initAll); if(typeof initAll==="function"){ initAll(); console.log("initAll called OK"); } else { console.log("initAll is", typeof initAll); } } catch(e) { console.log("initAll call error:", e.message); }';
    vm.runInContext(testCode, ctx);
    console.log('TEST OK');
} catch(e) {
    console.log('TEST ERROR:', e.message);
}
