"""Verify local page rendering before accepting a Chromium PDF screenshot."""

import re
from minem.chrome_pdf import capture_ready_page


ERROR_COLLECTOR = """<script>
window.minemPdfErrors=[];
addEventListener('error',event=>{
  if(event.target!==window || event.message)
    window.minemPdfErrors.push(event.message || event.target.src || event.target.href || '资源加载失败');
},true);
</script>"""

READY_SCRIPT = """<script>
document.addEventListener('DOMContentLoaded',()=>{
const frame=document.querySelector('iframe');
const stage=value=>{document.documentElement.dataset.pdfStage=value;};
stage('等待页面加载');
const imageLoaded=image=>new Promise((resolve,reject)=>{
  if(image.complete) return image.naturalWidth ? resolve() : reject(Error('图片加载失败'));
  image.addEventListener('load',resolve,{once:true});
  image.addEventListener('error',()=>reject(Error('图片加载失败')),{once:true});
  image.loading='eager';
});
const imageReady=async image=>{await imageLoaded(image);if(image.decode) await image.decode();};
async function inspect(doc){
  if(!doc || !doc.body) throw Error('页面未打开');
  if(doc.readyState!=='complete') await new Promise(resolve=>doc.defaultView.addEventListener('load',resolve,{once:true}));
  stage("等待字体");
  doc.body.getBoundingClientRect();
  await doc.fonts.ready;
  if(doc.defaultView.minemPdfErrors?.length) throw Error(doc.defaultView.minemPdfErrors[0]);
  stage("等待图片");
  await Promise.all(Array.from(doc.images,imageReady));
  stage("等待入场动效");
  await Promise.all(doc.getAnimations().filter(animation=>Number.isFinite(animation.effect?.getComputedTiming().endTime)).map(animation=>animation.finished.catch(()=>{})));
  stage("等待背景图片");
  const backgrounds=new Set();
  for(const element of doc.querySelectorAll('*')){
    const value=doc.defaultView.getComputedStyle(element).backgroundImage;
    for(const match of value.matchAll(/url\\(["']?(.*?)["']?\\)/g)) backgrounds.add(match[1]);
  }
  await Promise.all(Array.from(backgrounds,src=>{const image=new Image();image.src=src;return imageReady(image);}));
  await Promise.all(Array.from(doc.querySelectorAll('iframe'),child=>inspect(child.contentDocument)));
  for(const video of doc.querySelectorAll('video')){
    if(video.poster || (!video.getAttribute('src')&&!video.querySelector('source'))) continue;
    if(video.readyState<2) await new Promise((resolve,reject)=>{
      video.addEventListener('loadeddata',resolve,{once:true});
      video.addEventListener('error',()=>reject(Error('视频未能解码')),{once:true});
      video.preload='auto';video.load();
    });
    video.pause();
  }
}
const check=async()=>{
 try{
  await inspect(frame.contentDocument);
  stage('等待绘制');
  await new Promise(resolve=>setTimeout(resolve,150));
  document.documentElement.dataset.pdfReady='ready';
 }catch(error){document.documentElement.dataset.pdfError=error.message;}
};
frame.addEventListener('load',check,{once:true});
if(frame.contentDocument?.readyState==='complete' && frame.contentDocument.location.href!=='about:blank') check();
});
</script>"""


def add_pdf_checks(document):
    head = re.search(r"<head\b[^>]*>", document, re.I)
    return document[:head.end()] + ERROR_COLLECTOR + document[head.end():] if head else ERROR_COLLECTOR + document


def capture(chrome, wrapper, output):
    # Place the listener before the iframe so cached documents cannot finish first.
    document = wrapper.read_text(encoding="utf-8")
    document = document.replace("<iframe", READY_SCRIPT + "<iframe", 1)
    wrapper.write_text(document, encoding="utf-8")
    capture_ready_page(chrome, wrapper, output)
