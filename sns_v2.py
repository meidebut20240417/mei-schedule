import json,re,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
import requests

H={"User-Agent":"Mozilla/5.0"}
J=timezone(timedelta(hours=9))
YT="UCvTsv4KmVuBdECI08_HR87Q"
X="official__ME_I_"
IG="official_me_i_"
B="https://rss-bridge.org/bridge01"

def yt():
 r=requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={YT}",headers=H,timeout=30)
 n={"a":"http://www.w3.org/2005/Atom","y":"http://www.youtube.com/xml/schemas/2015"}
 root=ET.fromstring(r.content); out=[]
 for e in root.findall("a:entry",n)[:15]:
  v=e.findtext("y:videoId","",n)
  out.append({"id":"youtube_"+v,"platform":"youtube","platform_label":"YouTube","title":e.findtext("a:title","",n),"published_at":e.findtext("a:published","",n),"thumbnail":f"https://i.ytimg.com/vi/{v}/hqdefault.jpg","url":f"https://www.youtube.com/watch?v={v}"})
 return out

def x():
 d=requests.get(f"https://api.fxtwitter.com/2/profile/{X}/media?count=50",headers=H,timeout=30).json()
 out=[]
 for i in d.get("results",[]):
  p=(i.get("media") or {}).get("photos") or []
  if not p: continue
  u=p[0].get("url")
  if not u: continue
  out.append({"id":"x_"+str(i.get("id") or i.get("url")),"platform":"x","platform_label":"X","title":i.get("text") or "","published_at":i.get("created_at") or "","thumbnail":u,"url":i.get("url") or f"https://x.com/{X}"})
  if len(out)>=15: break
 return out

def ig():
 u=f"{B}/?action=display&bridge=InstagramBridge&context=Username&u={IG}&media_type=all&direct_links=on&format=Json"
 d=requests.get(u,headers=H,timeout=30).json(); out=[]; seen=set()
 for i in d.get("items",[]):
  link=str(i.get("url") or i.get("id") or "")
  if not link or link in seen: continue
  seen.add(link)
  h=str(i.get("content_html") or i.get("content") or "")
  imgs=re.findall(r'<img[^>]+src=["\']([^"\']+)',h,re.I)
  if not imgs: continue
  out.append({"id":"instagram_"+link,"platform":"instagram","platform_label":"Instagram","title":i.get("title") or "Instagram新着投稿","published_at":i.get("date_modified") or i.get("date_published") or "","thumbnail":imgs[0],"url":link})
  if len(out)>=15: break
 return out

def k(p):
 try:
  d=datetime.fromisoformat(str(p.get("published_at","")).replace("Z","+00:00"))
  return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
 except: return datetime.min.replace(tzinfo=timezone.utc)

p=yt()+x()+ig()
p.sort(key=k,reverse=True)
with open("sns.json","w",encoding="utf-8") as f: json.dump({"generated_at":datetime.now(J).isoformat(),"posts":p[:15]},f,ensure_ascii=False,indent=2)
print("counts", {x:sum(q["platform"]==x for q in p[:15]) for x in ("youtube","x","instagram")})
