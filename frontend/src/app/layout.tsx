import type { Metadata } from "next";

import "./globals.css";
import "../styles/00-foundation.css";
import "../styles/01-theme-templates.css";
import "../styles/02-workbench-shell.css";
import "../styles/03-workbench-primitives.css";
import "../styles/04-chat-workbench.css";
import "../styles/05-system-pages.css";
import "../styles/06-task-workbench.css";
import "../styles/07-agent-management.css";
import "@xyflow/react/dist/style.css";
import "../styles/08-graph-repository.css";

const APPEARANCE_BOOTSTRAP_SCRIPT = `(function(){try{
var root=document.documentElement;
var valid=["clean-light","warm-paper","ocean-breeze","mineral-gray","lavender-mist","focus-dark","midnight-ocean","charcoal-ember"];
var themeFonts={"clean-light":"system","warm-paper":"classic","ocean-breeze":"modern","mineral-gray":"system","lavender-mist":"rounded","focus-dark":"system","midnight-ocean":"modern","charcoal-ember":"rounded"};
var fonts=[
{id:"system",fd:'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", sans-serif',fm:'"Cascadia Mono", "Consolas", "SFMono-Regular", monospace'},
{id:"modern",fd:'"Inter", "Noto Sans SC", "Segoe UI Variable", -apple-system, system-ui, sans-serif',fm:'"JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", monospace'},
{id:"classic",fd:'"Noto Serif SC", "Source Serif 4", "Palatino Linotype", "Palatino", Georgia, serif',fm:'"Cascadia Mono", "Consolas", "SFMono-Regular", monospace'},
{id:"rounded",fd:'"Nunito", "Noto Sans SC", "PingFang SC", "Microsoft YaHei UI", system-ui, sans-serif',fm:'"Cascadia Mono", "Consolas", "SFMono-Regular", monospace'},
{id:"code-friendly",fd:'"SF Mono", "Cascadia Code", "JetBrains Mono", "Consolas", monospace',fm:'"SF Mono", "Cascadia Code", "JetBrains Mono", "Consolas", monospace'}
];
var tokens=["console-bg","console-bg-raised","console-surface","console-surface-muted","console-surface-strong","console-surface-soft","console-hover","console-selected","console-line","console-line-soft","console-line-strong","console-text","console-text-soft","console-muted","console-faint","console-accent","console-accent-hover","console-accent-soft","console-success","console-success-soft","console-warning","console-warning-soft","console-danger","console-danger-soft"];
var textVars={"console-text":["--console-text-font","--console-text-size"],"console-text-soft":["--console-text-soft-font","--console-text-soft-size"],"console-muted":["--console-muted-font","--console-muted-size"],"console-faint":["--console-faint-font","--console-faint-size"]};
function num(value,min,max,fallback){value=Number(value);return Number.isFinite(value)?Math.min(max,Math.max(min,value)):fallback}
function hex(value){return typeof value==="string"&&/^#[0-9a-f]{6}$/i.test(value.trim())?value.trim():""}
function family(value){return typeof value==="string"?value.trim().replace(/[;{}<>]/g,"").slice(0,180):""}
function bgLayout(hasImage){if(!hasImage)return["cover","center center","no-repeat"];return["cover","center top","no-repeat"]}
function setBgVars(hasImage){var l=bgLayout(hasImage);root.style.setProperty("--workbench-bg-size",l[0]);root.style.setProperty("--workbench-bg-position",l[1]);root.style.setProperty("--workbench-bg-repeat",l[2])}
function setBgVeilVars(hasImage,veil){var center=hasImage?Math.min(76,Math.max(0,veil)):veil;root.style.setProperty("--workbench-bg-veil-center",center+"%");root.style.setProperty("--workbench-bg-veil-edge",(hasImage?Math.min(90,Math.max(0,veil+22)):veil)+"%");root.style.setProperty("--workbench-bg-veil-top",(hasImage?Math.min(84,Math.max(0,veil+12)):veil)+"%");root.style.setProperty("--workbench-bg-veil-bottom",(hasImage?Math.min(96,Math.max(0,veil+40)):veil)+"%")}
function releaseBgObjectUrl(){var current=window.__workbenchBackgroundObjectUrl;if(!current)return;URL.revokeObjectURL(current.url);window.__workbenchBackgroundObjectUrl=undefined}
function dataUrlToBlob(value){var comma=value.indexOf(",");if(value.indexOf("data:")!==0||comma<0)return null;var head=value.slice(0,comma);var body=value.slice(comma+1);var mime=(head.match(/^data:([^;,]+)/i)||[])[1]||"application/octet-stream";var binary=/;base64/i.test(head)?atob(body):decodeURIComponent(body);var bytes=new Uint8Array(binary.length);for(var i=0;i<binary.length;i+=1){bytes[i]=binary.charCodeAt(i)}return new Blob([bytes],{type:mime})}
function bgPaintUrl(value){if(!(typeof value==="string"&&value.indexOf("data:")===0))return value;var current=window.__workbenchBackgroundObjectUrl;if(current&&current.source===value)return current.url;releaseBgObjectUrl();try{var blob=dataUrlToBlob(value);if(!blob)return value;var url=URL.createObjectURL(blob);window.__workbenchBackgroundObjectUrl={source:value,url:url};return url}catch(e){return value}}
var t=localStorage.getItem("workbenchTheme")||localStorage.getItem("workbench-theme")||"clean-light";
if(valid.indexOf(t)<0)t="clean-light";
root.setAttribute("data-workbench-theme",t);
var raw=localStorage.getItem("workbenchCustomSettings");
var o={};
if(raw){try{o=JSON.parse(raw)||{}}catch(e){o={}}}
var fontId=o.fontOverride||themeFonts[t]||"system";
var m=fonts.find(function(x){return x.id===fontId});
if(m){root.style.setProperty("--font-display",m.fd);root.style.setProperty("--font-mono",m.fm);root.style.setProperty("--console-font",m.fd);root.style.setProperty("--console-mono",m.fm);root.style.setProperty("--workbench-font",m.fd);root.style.setProperty("--workbench-font-mono",m.fm);root.style.setProperty("--font-sans",m.fd);root.style.setProperty("--font-brand-latin",m.fd)}
var scale=num(o.fontSizeScale,0.8,1.3,1);
root.style.setProperty("--console-font-size-ui",Math.round(15*scale)+"px");
root.style.setProperty("--console-font-size-page",Math.round(16*scale)+"px");
root.style.setProperty("--console-font-size-body",Math.round(17*scale)+"px");
root.style.fontSize=Math.round(15*scale)+"px";
var bgImage=typeof o.bgImage==="string"&&o.bgImage.trim()?o.bgImage.trim():"";
if(bgImage){root.style.setProperty("--workbench-bg-image","url("+JSON.stringify(bgPaintUrl(bgImage))+")")}else{releaseBgObjectUrl();root.style.setProperty("--workbench-bg-image","none")}
setBgVars(!!bgImage);
if(o.customColorsEnabled===true){var overrides=o.colorOverrides&&typeof o.colorOverrides==="object"?o.colorOverrides:null;if(overrides){tokens.forEach(function(token){var color=hex(overrides[token]);if(color)root.style.setProperty("--"+token,color)})}else{if(hex(o.bgColor))root.style.setProperty("--console-bg",hex(o.bgColor));if(hex(o.panelColor)){root.style.setProperty("--console-surface",hex(o.panelColor));root.style.setProperty("--console-bg-raised",hex(o.panelColor))}if(hex(o.accentSoftColor))root.style.setProperty("--console-accent-soft",hex(o.accentSoftColor))}}
var textOverrides=o.textStyleOverrides&&typeof o.textStyleOverrides==="object"?o.textStyleOverrides:{};
Object.keys(textVars).forEach(function(token){var style=textOverrides[token];if(!style||typeof style!=="object")return;var vars=textVars[token];var f=family(style.fontFamily);var size=num(style.fontSizePx,10,32,0);if(f)root.style.setProperty(vars[0],f);if(size)root.style.setProperty(vars[1],Math.round(size)+"px")});
var veil=Math.round(num(o.chatCanvasVeil,0,90,34));
var surface=Math.round(num(o.chatSurfaceOpacity,35,100,72));
root.style.setProperty("--chat-canvas-veil",veil+"%");
root.style.setProperty("--chat-canvas-veil-soft",Math.max(0,veil-14)+"%");
setBgVeilVars(!!bgImage,veil);
root.style.setProperty("--chat-panel-surface-alpha",surface+"%");
root.style.setProperty("--chat-panel-surface-alpha-soft",Math.max(0,surface-18)+"%");
root.style.setProperty("--workspace-bg-texture-opacity",String(Math.round(num(o.textureIntensity,0,100,100))/100));
root.style.setProperty("--closeout-content-max",Math.round(num(o.closeoutMaxWidth,860,1480,1180))+"px");
root.style.colorScheme=["focus-dark","midnight-ocean","charcoal-ember"].indexOf(t)>=0?"dark":"light";
}catch(e){}})()`;

export const metadata: Metadata = {
  title: "Mythical Age | 洪荒智能",
  description: "洪荒智能：透明、文件优先的本地 AI agent 系统。",
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html data-workbench-density="standard" data-workbench-theme="clean-light" lang="zh-CN" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Nunito:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;500;700&display=swap" rel="stylesheet" />
      </head>
      <body>
        <script dangerouslySetInnerHTML={{
          __html: APPEARANCE_BOOTSTRAP_SCRIPT,
        }} />
        {children}
      </body>
    </html>
  );
}
