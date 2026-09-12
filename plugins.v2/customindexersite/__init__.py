import base64
import json
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
    plugin_version = "1.2"
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
        """
        created = []
        site_oper = SiteOper()
        siteshelper = SitesHelper()
        for domain in [d.strip() for d in self._ensure_sites.split(",") if d.strip()]:
            try:
                indexer = siteshelper.get_indexer(domain)
                if not indexer:
                    logger.warn(f"站点 {domain} 没有可用的索引器模板，跳过创建站点记录")
                    continue
                if site_oper.get_by_domain(domain):
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
                if site_oper.get_by_domain(domain):
                    created.append(domain)
                    logger.info(f"站点记录已创建：{domain}（{indexer.get('name')}）")
                else:
                    logger.warn(f"站点记录创建失败：{domain}")
            except Exception as err:
                logger.error(f"创建站点记录 {domain} 出错：{err}")
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
