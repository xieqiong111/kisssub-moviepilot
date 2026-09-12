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
    plugin_version = "1.4"
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
                local_templates = {}
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
                        local_templates[domain] = indexer_conf
                        logger.info(
                            f"自定义索引站点已加载：{domain}（{indexer_conf.get('name')}）")
                    except Exception as err:
                        logger.error(f"自定义索引站点配置错误：{err}")
                # 2、为指定域名创建站点记录（已存在则跳过）
                #    ensure_sites 条目格式：domain 或 domain:名称；自有模板优先
                if self._ensure_sites:
                    created = self.__ensure_sites(local_templates)
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

    def __ensure_sites(self, local_templates: dict = None) -> List[str]:
        """
        为 ensure_sites 中的域名直接创建站点记录。
        条目格式：domain 或 domain:名称。
        优先使用本插件注入的自有模板信息，不依赖 SitesHelper 返回模板。
        每步结果写入插件数据 last_run 供远程诊断。
        """
        diag = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

        def _diag(step, detail):
            diag["steps"].append({"step": step, "detail": str(detail)[:300]})
            logger.info(f"[自定义索引站点][{step}] {str(detail)[:200]}")

        created = []
        local_templates = local_templates or {}

        # 站点信息来源：自有模板 + ensure 条目自带名称
        entries = []
        for domain in [d.strip() for d in self._ensure_sites.split(",") if d.strip()]:
            if ":" in domain:
                dom, _, name = domain.partition(":")
                entries.append((dom.strip(), name.strip()))
            else:
                entries.append((domain, None))

        try:
            site_oper = SiteOper()
            _diag("site_oper", "SiteOper 初始化成功")
        except Exception as err:
            _diag("site_oper", f"初始化失败: {err}")
            self.save_data("last_run", diag)
            return []

        for dom, given_name in entries:
            try:
                existed = site_oper.get_by_domain(dom)
                if existed:
                    _diag(f"create:{dom}", f"记录已存在 id={existed.id}")
                    continue
                tpl = local_templates.get(dom) or {}
                name = tpl.get("name") or given_name or dom
                url = tpl.get("domain") or f"https://{dom}/"
                site_oper.add(
                    name=name,
                    url=url,
                    domain=dom,
                    cookie=self._site_cookie or None,
                    ua=self._site_ua or None,
                    pri=100,
                    public=1 if tpl.get("public") else 0,
                )
                after = site_oper.get_by_domain(dom)
                if after:
                    created.append(dom)
                    _diag(f"create:{dom}", f"创建成功 id={after.id} name={name}")
                else:
                    _diag(f"create:{dom}", "创建后查询不到，失败")
            except Exception as err:
                _diag(f"create:{dom}", f"出错: {err}")

        # 关键诊断：建站后 SitesHelper 是否能看到这些站点（决定搜索是否可用）
        try:
            all_indexers = SitesHelper().get_indexers()
            count = len(all_indexers) if all_indexers else 0
            seen = []
            if all_indexers:
                items = (all_indexers if isinstance(all_indexers, list)
                         else list(all_indexers.values()) if isinstance(all_indexers, dict)
                         else [])
                for t in items:
                    if isinstance(t, dict):
                        seen.append(t.get("domain") or t.get("id"))
            hits = [s for s in seen if s and ("kisssub" in str(s) or "mikanani" in str(s))]
            _diag("after_create", f"get_indexers 数量={count}, 目标站点可见={hits}")
        except Exception as err:
            _diag("after_create", f"出错: {err}")

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
                                            'placeholder': '逗号分隔，支持 域名 或 域名:名称，如：kisssub.org,mikanani.me:蜜柑计划'
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
                                                    '"自动创建站点记录的域名"中的记录只会创建一次，已存在的不重复创建。'
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
