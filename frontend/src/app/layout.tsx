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
function imageMeta(value){if(!value||typeof value!=="object")return null;var w=Number(value.width),h=Number(value.height);if(!Number.isFinite(w)||!Number.isFinite(h)||w<=0||h<=0)return null;return{width:Math.round(w),height:Math.round(h),aspectRatio:Number((w/h).toFixed(4))}}
function bgLayout(hasImage,meta){var balanced="linear-gradient(90deg, transparent 0%, black 18%, black 82%, transparent 100%)";var right="linear-gradient(90deg, transparent 0%, black 34%, black 100%)";if(!hasImage)return["cover","center center","cover","center center","contain","center center","0",balanced];if(!meta)return["auto 100%","right center","cover","center center","auto min(92%, 960px)","right center","0.32",right];var ratio=meta.aspectRatio||meta.width/meta.height;if(ratio<1)return["auto 100%","right center","cover","center center","auto min(94%, 980px)","right center","0.34",right];if(ratio<1.35)return["auto 100%","right center","cover","center center","auto min(90%, 980px)","right center","0.3",right];return["cover","center center","cover","center center","contain","center center","0.24",balanced]}
function setBgVars(hasImage,meta){var l=bgLayout(hasImage,meta);root.style.setProperty("--workbench-bg-size",l[0]);root.style.setProperty("--workbench-bg-position",l[1]);root.style.setProperty("--workbench-bg-atmosphere-size",l[2]);root.style.setProperty("--workbench-bg-atmosphere-position",l[3]);root.style.setProperty("--workbench-bg-subject-size",l[4]);root.style.setProperty("--workbench-bg-subject-position",l[5]);root.style.setProperty("--workbench-bg-subject-opacity",l[6]);root.style.setProperty("--workbench-bg-subject-mask",l[7])}
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
root.style.setProperty("--workbench-bg-image",bgImage?"url("+JSON.stringify(bgImage)+")":"none");
setBgVars(!!bgImage,imageMeta(o.bgImageMeta));
if(o.customColorsEnabled===true){var overrides=o.colorOverrides&&typeof o.colorOverrides==="object"?o.colorOverrides:null;if(overrides){tokens.forEach(function(token){var color=hex(overrides[token]);if(color)root.style.setProperty("--"+token,color)})}else{if(hex(o.bgColor))root.style.setProperty("--console-bg",hex(o.bgColor));if(hex(o.panelColor)){root.style.setProperty("--console-surface",hex(o.panelColor));root.style.setProperty("--console-bg-raised",hex(o.panelColor))}if(hex(o.accentSoftColor))root.style.setProperty("--console-accent-soft",hex(o.accentSoftColor))}}
var textOverrides=o.textStyleOverrides&&typeof o.textStyleOverrides==="object"?o.textStyleOverrides:{};
Object.keys(textVars).forEach(function(token){var style=textOverrides[token];if(!style||typeof style!=="object")return;var vars=textVars[token];var f=family(style.fontFamily);var size=num(style.fontSizePx,10,32,0);if(f)root.style.setProperty(vars[0],f);if(size)root.style.setProperty(vars[1],Math.round(size)+"px")});
var veil=Math.round(num(o.chatCanvasVeil,0,90,34));
var surface=Math.round(num(o.chatSurfaceOpacity,35,100,72));
root.style.setProperty("--chat-canvas-veil",veil+"%");
root.style.setProperty("--chat-canvas-veil-soft",Math.max(0,veil-14)+"%");
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
