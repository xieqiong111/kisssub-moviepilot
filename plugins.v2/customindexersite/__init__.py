import base64
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.db.site_oper import SiteOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase


class CustomIndexerSite(_PluginBase):
    # 插件名称
    plugin_name = "自定义索引站点"
    # 插件描述
    plugin_desc = "修改或扩展内建索引器支持的站点，支持注入自定义索引器并自动创建站点记录，无需站点认证。"
    # 插件版本
    plugin_version = "1.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "customindexersite_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    # 0 = 不依赖 MoviePilot 站点认证：本插件只注入索引器模板和创建站点记录
    auth_level = 0

    # 私有属性
    _enabled = False
    _confstr = ""
    _ensure_sites = ""
    _site_cookie = ""
    _site_ua = ""
    _restart_after_create = False

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled") or False
            self._confstr = config.get("confstr") or ""
            self._ensure_sites = config.get("ensure_sites") or ""
            self._site_cookie = config.get("site_cookie") or ""
            self._site_ua = config.get("site_ua") or ""
            self._restart_after_create = config.get("restart_after_create") or False
            if self._enabled:
                created = []
                # 1、注入索引器：一行一个站点，域名|索引配置JSON的base64编码(utf-8)
                for indexer in self._confstr.split("\n"):
                    if not indexer.strip():
                        continue
                    try:
                        domain, jsonstr = indexer.split("|", 1)
                        domain = domain.strip()
                        jsonstr = jsonstr.strip()
                        if not domain or not jsonstr:
                            continue
                        indexer_conf = json.loads(
                            base64.b64decode(jsonstr).decode("utf-8"))
                        SitesHelper().add_indexer(domain, indexer_conf)
                        logger.info(
                            f"自定义索引站点已加载：{domain}（{indexer_conf.get('name')}）")
                    except Exception as err:
                        logger.error(f"自定义索引站点配置错误：{err}")
                # 2、为指定域名创建站点记录（已存在则跳过）
                if self._ensure_sites:
                    created = self.__ensure_sites()
                # 3、新建了站点记录且允许时，重启使内建缓存生效
                if created and self._restart_after_create:
                    try:
                        from app.helper.system import SystemHelper
                        logger.info(f"已创建站点记录 {created}，重启 MoviePilot 生效...")
                        SystemHelper.restart()
                    except Exception as err:
                        logger.error(f"重启 MoviePilot 失败：{err}")
        else:
            self._enabled = False
            self._confstr = ""
            self._ensure_sites = ""
            self._site_cookie = ""
            self._site_ua = ""
            self._restart_after_create = False

    def __ensure_sites(self) -> List[str]:
        """
        为 ensure_sites 中的域名创建站点记录（需要有可用索引器模板，含内建或本插件注入的）
        每一步结果写入插件数据 last_run，便于远程诊断。
        """
        diag = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

        def _diag(step, detail):
            diag["steps"].append({"step": step, "detail": str(detail)[:300]})
            logger.info(f"[自定义索引站点][{step}] {str(detail)[:200]}")

        created = []
        siteshelper = SitesHelper()
        try:
            all_indexers = siteshelper.get_indexers()
            if isinstance(all_indexers, dict):
                _diag("indexers", f"共 {len(all_indexers)} 个模板")
            else:
                _diag("indexers", f"get_indexers 返回 {type(all_indexers).__name__}, 数量 {len(all_indexers) if all_indexers else 0}")
        except Exception as err:
            all_indexers = None
            _diag("indexers", f"获取模板列表出错: {err}")

        def _find_template(domain):
            # 优先 get_indexer，失败则从 get_indexers() 中按域名匹配
            try:
                t = siteshelper.get_indexer(domain)
                if t:
                    return t
            except Exception as err:
                _diag(f"get_indexer({domain})", f"出错: {err}")
            if isinstance(all_indexers, dict):
                if domain in all_indexers:
                    return all_indexers[domain]
                for k, v in all_indexers.items():
                    if k.endswith(domain) or domain.endswith(k):
                        return v
            elif isinstance(all_indexers, list):
                for t in all_indexers:
                    if isinstance(t, dict) and (t.get("domain", "").endswith(domain) or domain in t.get("domain", "")):
                        return t
            return None

        try:
            site_oper = SiteOper()
            _diag("site_oper", "SiteOper 初始化成功")
        except Exception as err:
            _diag("site_oper", f"初始化失败: {err}")
            self.save_data("last_run", diag)
            return []

        for domain in [d.strip() for d in self._ensure_sites.split(",") if d.strip()]:
            try:
                indexer = _find_template(domain)
                if not indexer:
                    _diag(f"template:{domain}", "未找到索引器模板")
                    continue
                _diag(f"template:{domain}", f"找到模板: {indexer.get('name')}")
                existed = site_oper.get_by_domain(domain)
                if existed:
                    _diag(f"create:{domain}", f"记录已存在 id={existed.id}")
                    continue
                site_oper.add(
                    name=indexer.get("name") or domain,
                    url=indexer.get("domain") or f"https://{domain}/",
                    domain=domain,
                    cookie=self._site_cookie or None,
                    ua=self._site_ua or None,
                    pri=100,
                    public=1 if indexer.get("public") else 0,
                )
                after = site_oper.get_by_domain(domain)
                if after:
                    created.append(domain)
                    _diag(f"create:{domain}", f"创建成功 id={after.id}")
                else:
                    _diag(f"create:{domain}", "创建后查询不到，失败")
            except Exception as err:
                _diag(f"create:{domain}", f"出错: {err}")

        try:
            self.save_data("last_run", diag)
        except Exception as err:
            logger.error(f"保存诊断数据失败：{err}")
        return created

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'restart_after_create',
                                            'label': '创建站点记录后自动重启',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'confstr',
                                            'label': '站点索引配置',
                                            'rows': 6,
                                            'placeholder': '一行一个站点，配置格式：域名|配置json的base64编码（utf-8）'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ensure_sites',
                                            'label': '自动创建站点记录的域名',
                                            'placeholder': '多个域名用英文逗号分隔，如：kisssub.org,mikanani.me'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'site_cookie',
                                            'label': '站点Cookie（留空则不带Cookie）',
                                            'placeholder': '如：visitor_test=human'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'site_ua',
                                            'label': '站点UA（留空使用默认）',
                                            'placeholder': 'Chrome UA'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '域名只取后两段，如：www.kisssub.org 只需填写 kisssub.org；'
                                                    '索引配置JSON需使用utf-8进行base64编码；'
                                                    '如站点域名已被内建索引器支持，则会覆盖内建配置；'
                                                    '"自动创建站点记录的域名"中的域名需已有索引器模板（内建或本插件注入的），'
                                                    '记录只会创建一次，已存在的不重复创建。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "confstr": "",
            "ensure_sites": "",
            "site_cookie": "",
            "site_ua": "",
            "restart_after_create": False
        }

    def get_page(self) -> Optional[List[dict]]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
