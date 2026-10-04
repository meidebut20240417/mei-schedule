import json,re,requests
from datetime import datetime,timezone

class _Node:
    def __init__(self,url):
        self.is_video=False
        self.display_url=url

class _Post:
    def __init__(self,shortcode,title,when,images):
        self.shortcode=shortcode
        self.typename="GraphSidecar" if len(images)>1 else "GraphImage"
        self._images=images
        self.caption=title
        self.is_video=False
        self.url=images[0] if images else ""
        self.date_utc=when
    def get_sidecar_nodes(self):
        return [_Node(x) for x in self._images]

class _Context:
    def __init__(self):
        self.user_agent=""
        self._session=requests.Session()

class Instaloader:
    def __init__(self,*args,**kwargs):
        self.context=_Context()

class Profile:
    @staticmethod
    def from_username(context,username):
        return _Profile(username)

class _Profile:
    def __init__(self,username):
        self.username=username
    def get_posts(self):
        url=("https://rss-bridge.org/bridge01/?action=display&bridge=InstagramBridge"
             "&context=Username&u="+self.username+"&media_type=all&direct_links=on&format=Json")
        data=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=30).json()
        for item in data.get("items",[]):
            html=str(item.get("content_html") or item.get("content") or "")
            images=re.findall(r'<img[^>]+src=["\']([^"\']+)',html,re.I)
            images=[x for x in images if x.startswith(("http://","https://"))]
            if not images:
                continue
            link=str(item.get("url") or item.get("id") or "")
            m=re.search(r"/p/([^/?#]+)/?",link)
            shortcode=m.group(1) if m else link.rsplit("/",1)[-1]
            value=str(item.get("date_modified") or item.get("date_published") or "")
            try:
                when=datetime.fromisoformat(value.replace("Z","+00:00")).replace(tzinfo=None)
            except Exception:
                when=datetime.min
            yield _Post(shortcode,str(item.get("title") or ""),when,images)
