import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase


class CustomIndexerSite(_PluginBase):
    # 插件名称
    plugin_name = "自定义索引站点"
    # 插件描述
    plugin_desc = "修改或扩展内建索引器支持的站点，可用于添加官方未适配的站点（如：爱恋动漫 kisssub.org）。"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "customindexersite_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    _enabled = False
    _confstr = ""

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled") or False
            self._confstr = config.get("confstr") or ""
            if self._enabled and self._confstr:
                # 配置生效，一行一个站点：域名|索引配置JSON的base64编码(utf-8)
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
        else:
            self._enabled = False
            self._confstr = ""

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
                                            'rows': 10,
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
                                                    '如站点域名已被内建索引器支持，则会覆盖内建配置。'
                                                    '保存后到「站点管理」新增站点即可。'
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
            "confstr": ""
        }

    def get_page(self) -> Optional[List[dict]]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass
