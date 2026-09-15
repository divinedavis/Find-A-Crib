#!/usr/bin/env python3
"""Apple preview lifecycle tests using a stub SDK; no Apple quota is consumed."""
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
MODULE=(ROOT/'static/apple-street-preview.js').read_text()
FRAME=(ROOT/'static/apple-street-frame.html').read_text()
HTML='''<style>.tile{position:relative;width:300px;height:150px;margin:10px}.apple-street-preview{position:absolute;inset:0}[hidden]{display:none!important}</style>
<div id="tiles"></div><script>window.testCreated=0;window.testDestroyed=0;window.testLoading=0;window.testMaxLoading=0;</script><script src="/apple.js"></script>'''
SDK='''
class Preview extends EventTarget {
 constructor(host,coordinate,options){super();parent.testCreated++;parent.testLoading++;
 parent.testMaxLoading=Math.max(parent.testMaxLoading,parent.testLoading);
 this.element=document.createElement('div');this.element.textContent='Apple SDK test fixture';host.appendChild(this.element);
 this.openDialog=false;this.readyState='loading';this.pending=true;
 parent.testCoordinates?.push(coordinate.latitude);
 parent.testOptions=options;
 this.element.addEventListener('click',()=>{this.openDialog=true;this.dispatchEvent(new Event('enter-dialog'));});
 this.timer=setTimeout(()=>{this.pending=false;parent.testLoading--;this.readyState=coordinate.latitude<39?'error':'complete';this.dispatchEvent(new Event(this.readyState==='error'?'error':'load'));},coordinate.latitude===41?1000:30);}
 destroy(){clearTimeout(this.timer);if(this.pending){parent.testLoading--;this.pending=false;}parent.testDestroyed++;this.element.remove();this.readyState='destroyed';}
}
window.mapkit={LookAroundPreview:Preview,Coordinate:class{constructor(lat,lng){this.latitude=lat;this.longitude=lng;}}};
window[document.currentScript.dataset.callback]();'''
def main():
 with sync_playwright() as p:
  for name in ('chromium','webkit'):
   browser=getattr(p,name).launch()
   page=browser.new_page(viewport={'width':390,'height':844})
   errors=[];sdk_requests=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   def app(route):
    route.fulfill(content_type='application/javascript' if '/apple.js' in route.request.url else 'text/html',body=MODULE if '/apple.js' in route.request.url else FRAME if '/static/apple-street-frame.html' in route.request.url else HTML)
   page.route('http://localhost/**',app)
   def sdk(route):
    sdk_requests.append(True);route.fulfill(content_type='application/javascript',body=SDK)
   page.route('https://cdn.apple-mapkit.com/**',sdk)
   page.goto('http://localhost/?photos=apple')
   def render(lat=40,count=1):
    page.evaluate('''([lat,count])=>{const host=document.getElementById('tiles');host.innerHTML=Array.from({length:count},()=>'<div class="tile">'+AppleStreetPreview.html({lat,lng:-73,a:'Test address'})+'</div>').join('');AppleStreetPreview.watch(host);}''',[lat,count])
   render()
   page.get_by_text('Connect Apple Maps to preview photos',exact=True).wait_for()
   assert not sdk_requests
   page.evaluate("sessionStorage.setItem('fac.apple_maps_token','test.web.token')")
   page.reload();render(count=4)
   page.wait_for_function('parent.testCreated===4 && parent.testLoading===0')
   assert len(sdk_requests)==4
   # 5 since 2026-09-15: three at a time left visible cards queued behind each
   # other, and Safari never finishes an off-screen preview, so the slot that
   # used to warm the next row jammed the queue for 45 s.
   assert page.evaluate('parent.testMaxLoading')<=5
   assert page.locator('.apple-street-status:not([hidden])').count()==0
   assert page.evaluate('parent.testOptions.isNavigationEnabled && parent.testOptions.isScrollEnabled && parent.testOptions.isZoomEnabled')
   attrs=page.locator('iframe').first.content_frame.locator('script[data-libraries]').evaluate('(el)=>({libraries:el.dataset.libraries,token:el.dataset.token})')
   assert attrs=={'libraries':'look-around','token':'test.web.token'}
   first_frame=page.locator('iframe').first
   first_frame.content_frame.get_by_text('Apple SDK test fixture').click()
   page.wait_for_function('document.querySelector("iframe").matches(":popover-open")')
   assert first_frame.evaluate('(f)=>f.clientWidth')==390
   page.evaluate('AppleStreetPreview.close(document.getElementById("tiles"))')
   page.wait_for_function('!document.querySelector("iframe").hasAttribute("popover")')
   assert page.locator('iframe').count()==4, 'Closing the viewer should keep its iframe available for deferred cleanup'
   first_frame.content_frame.get_by_text('Apple SDK test fixture').click()
   page.wait_for_function('document.querySelector("iframe").matches(":popover-open")')
   page.keyboard.press('Escape')
   page.wait_for_function('!document.querySelector("iframe").hasAttribute("popover")')
   assert first_frame.evaluate('(f)=>f.clientWidth')==300
   render(38)
   page.get_by_text('Apple street imagery is unavailable here',exact=True).wait_for()
   assert page.locator('iframe').count()==0
   page.evaluate("document.getElementById('tiles').style.marginTop='2000px'")
   before=page.evaluate('parent.testCreated');render(40)
   page.wait_for_timeout(100)
   assert page.evaluate('parent.testCreated')==before
   page.locator('.tile').scroll_into_view_if_needed()
   page.wait_for_function('parent.testLoading===0 && document.querySelector(".apple-street-status").hidden')
   assert page.evaluate('parent.testCreated')==before+1
   # Warm the next row inside the actual scrolling grid; do not warm distant rows.
   page.reload()
   page.evaluate("""()=>{window.testCoordinates=[];const host=document.getElementById('tiles');
    host.innerHTML='<div id="grid" style="height:170px;overflow:auto"></div>';
    const grid=document.getElementById('grid');grid.innerHTML=Array.from({length:10},(_,i)=>'<div class="tile">'+AppleStreetPreview.html({lat:40+i/100,lng:-73})+'</div>').join('');AppleStreetPreview.watch(grid);}""")
   page.wait_for_function('window.testCoordinates.length>=3 && window.testLoading===0')
   assert page.evaluate('window.testCoordinates[0]')==40
   assert page.evaluate('window.testCoordinates.length')<=4
   assert page.evaluate('window.testMaxLoading')<=3
   warmed=page.evaluate('window.testCreated')
   page.evaluate("document.getElementById('grid').scrollTop=160")
   page.locator('#grid .tile').nth(1).locator('.apple-street-status[hidden]').wait_for(state='attached')
   # A slow photo left far behind is cancelled so it cannot block a new row.
   page.reload()
   page.evaluate("""()=>{window.testCoordinates=[];const host=document.getElementById('tiles');
    host.innerHTML='<div id="grid" style="height:150px;overflow:auto"></div>';
    const grid=document.getElementById('grid');grid.innerHTML=Array.from({length:14},(_,i)=>'<div class="tile">'+AppleStreetPreview.html({lat:i===0?41:42+i/100,lng:-73})+'</div>').join('');AppleStreetPreview.watch(grid);}""")
   page.wait_for_function('window.testCoordinates.includes(41)')
   page.evaluate("document.getElementById('grid').scrollTop=1600")
   page.wait_for_function("!document.querySelector('[data-apple-lat=\"41\"] iframe')")
   page.wait_for_function('window.testCoordinates.some(lat=>lat>=42.09)')
   before_requests=len(sdk_requests)
   # Default local and production pages use Apple; Mapillary stays opt-in locally.
   page.goto('http://localhost/')
   assert page.evaluate('AppleStreetPreview.enabled')
   page.goto('http://localhost/?photos=mapillary')
   assert not page.evaluate('AppleStreetPreview.enabled')
   page.route('https://findacrib.com/**',app)
   page.goto('https://findacrib.com/')
   assert page.evaluate('AppleStreetPreview.enabled')
   render()
   page.get_by_text('Street photo temporarily unavailable',exact=True).wait_for()
   assert not page.locator('a[href="/apple-preview/"]').count()
   assert len(sdk_requests)==before_requests
   page.add_init_script("window.APPLE_MAPS_TOKEN='test.web.token'")
   page.reload();render()
   page.wait_for_function('document.querySelector(".apple-street-status").hidden')
   assert page.locator('iframe').count()==1
   page.evaluate('AppleStreetPreview.release(document.getElementById("tiles"))')
   assert page.locator('iframe').count()==0
   page.route('https://unrelated.example/**',app)
   page.goto('https://unrelated.example/')
   assert not page.evaluate('AppleStreetPreview.enabled')
   assert not errors, errors
   print(f'PASS {name}: token setup, isolated frames, lazy initialization, concurrency, cleanup, coverage errors, hostname gating',flush=True)
   browser.close()
if __name__=='__main__':main()
