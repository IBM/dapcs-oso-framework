#
# (c) Copyright IBM Corp. 2025
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import contextlib

from abc import ABC
from inspect import isabstract
from collections.abc import Mapping, MutableMapping, Sequence
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Union,
    get_args,
    get_origin,
    override,
)

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    ImportString,
    Tag,
    ValidationError,
    create_model,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)


class _EnvSourceListSupport(EnvSettingsSource):
    """Add support for array indexed keys.

    Adds support for :py:class:~`typing.Sequence` like types in environment variables.
    """

    @override
    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: Any,
        value_is_complex: bool,
    ) -> Any:
        prepared = super().prepare_field_value(
            field_name,
            field,
            value,
            value_is_complex,
        )
        if prepared:
            anno = field.annotation
            if isinstance(anno, type) and issubclass(anno, BaseModel):
                # Nested BaseModel
                for k, v in anno.model_fields.items():
                    o = get_origin(v.annotation)
                    if isinstance(o, type) and issubclass(o, Sequence):
                        with contextlib.suppress(KeyError):
                            prepared[k] = list(prepared[k].values())
                return prepared
            o = get_origin(field.annotation)
            if isinstance(o, type) and issubclass(o, Sequence):
                return list(prepared.values())
        # Return the original prepared value
        return prepared


class _Config(BaseSettings, ABC):
    """Helper class that utilizes the `._EnvSourceListSupport` source."""

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        assert (
            init_settings and env_settings and dotenv_settings and file_secret_settings
        )
        return (_EnvSourceListSupport(settings_cls, env_nested_delimiter="__"),)


def _isimportable(kls: Any) -> bool:
    """Is class importable.

    Check if ``kls`` is of type ~`pyandic.ImportString` or `.ImportableConfig`, or a
    ~`typing.Sequence` of either.

    Parameters
    ----------
    kls : ~`typing.Any`
        Class to be checked.

    Returns
    -------
    bool
        If `kls` is importable.

    Notes
    -----
    Some :py:mod:`pydantic.typing` are just `typing.Annotated` types, as is
    `pydanticImportString`; so `inspect.issubclass` raises type hint errors, which
    is why the check is using ``is`` instead.
    """
    if isinstance(kls, type):
        return kls is ImportString or issubclass(kls, ImportableConfig)
    origin, args = get_origin(kls), get_args(kls)
    return (
        isinstance(origin, type)
        and issubclass(origin, Sequence)
        and len(args) > 0
        and _isimportable(args[0])
    )


def _construct_intermediary(
    field_or_model: FieldInfo | type[BaseModel],
    *keys: str,
) -> type[BaseModel]:
    """Create a new intermediary type chain.

    Parameters
    ----------
    field_or_model : ~`pydantic.FieldInfo` | type[~`pydantic.BaseModel`]
        The model that needs to be embeded in a nested models.
    *keys : str
        The chain of field names the final model is nested under.
    """
    _keys = list(keys)
    _key = _keys.pop()
    if isinstance(field_or_model, FieldInfo):
        _type = field_or_model.annotation
        _field = field_or_model
    else:
        _type = field_or_model
        _field = Field(default_factory=_type)
    if o := get_origin(_type):
        if issubclass(o, Sequence):
            if issubclass(get_args(_type)[0], ImportableConfig):
                _type = Sequence[ImportableConfig]
    _model = create_model(
        f"_intermediate_{_key}",
        **{_key: (_type, _field)},  # type: ignore
    )
    if len(_keys):
        return _construct_intermediary(_model, *_keys)
    return _model


def _discriminate(to_import: Any) -> str:
    """Discriminate against `.ImportableConfig` types.

    Parameters
    ----------
    to_import : ~`typing.Any`
        The model that needs it's type to be determined.

    Returns
    -------
    str
        The model's type.
    """
    if isinstance(to_import, dict):
        return to_import["type"]
    return getattr(to_import, "type", "None")


class AutoLoadConfig(BaseModel, ABC):
    """Config that is registered on import.

    A configuration model that will be automatically registered with `.ConfigManager`
    when imported.

    Attributes
    ----------
    __config_prefix__ : ~`typing.ClassVar`[str]
        If set to an empty string, the configuration model's fields will be added to
        the root model. Otherwise, the configuration model will be added to the root
        model under this value, merged with other configuration models with the same
        value.
    """

    __config_prefix__: ClassVar[str]

    @classmethod
    @override
    def __init_subclass__(cls, _config_prefix: str = "", **kwargs):
        super().__init_subclass__(**kwargs)

    @classmethod
    @override
    def __pydantic_init_subclass__(cls, _config_prefix: str = "", **kwargs):
        if not isabstract(cls):
            if not hasattr(cls, "__config_prefix__") or _config_prefix != "":
                cls.__config_prefix__ = _config_prefix
        ConfigManager._add(cls)
        super().__pydantic_init_subclass__(**kwargs)


class ImportableConfig(BaseModel, ABC):
    """Config object that defines an type import.

    Defines an configuration model that is importable with additional configuration
    fields. This is resolved to a fully discriminated type when configuration is
    rendered.

    Attributes
    ----------
    __importable_subclasses__: ClassVar[set[type[Any]]]
        A set of classes that subclass this.
    type : pydantic.ImportString
        The module that is required.
    """

    __importable_subclasses__: ClassVar[set[type[Any]]] = set()
    type: ImportString

    @classmethod
    @override
    def __pydantic_init_subclass__(cls, **kwargs):
        cls._register_config()
        super().__pydantic_init_subclass__(**kwargs)

    @classmethod
    def _register_config(cls):
        """Register this subclass as part of a parent."""
        cls.__importable_subclasses__ = set()
        for c in cls.__mro__:
            if c is not cls and issubclass(c, ImportableConfig):
                c.__importable_subclasses__.add(cls)

    @classmethod
    def _get_type(cls) -> Annotated:
        """Concrete type union with discriminator tags.

        Returns
        -------
        ~`typing.Annotated`
            An ~`typing.Annotated` type of ~`typing.Union` of all subclasses that is
            registered to a parent class with all of the discriminating tags. If only
            one exists, then the `~typing.Union` and ~`pydantic.Discriminator` is left
            out.
        """
        _anno = list(
            Annotated[kls, Tag(kls.__module__)] for kls in cls.__importable_subclasses__
        )
        _anno.append(Annotated[ImportableConfig, Tag("None")])
        if len(_anno) == 1:
            return _anno[0]
        return Annotated[Union[*_anno], Discriminator(_discriminate)]


class _ImportList(BaseModel):
    """Helper class for `.ImportableConfig`.

    Helper class that remembers all `collections.abc.Sequence`[`.ImportableConfig`]
    fields that need to be realized before configuration is rendered. This should not be
    used by itself, rather with the `.ImportListMixin` function.

    Attributes
    ----------
    __importable_fields_map__
    : ~`typing.ClassVar`[~`collections.abc.Mapping`[str, type[`.ImportableConfig`]]]
        A mapping of fields.
    """

    __importable_fields_map__: ClassVar[Mapping[str, type[ImportableConfig]]]

    @classmethod
    def _realize(cls):
        for k, v in cls.__importable_fields_map__.items():
            cls.model_fields[k].annotation = Sequence[v._get_type()]


def ImportListMixin(fields: Mapping[str, type[ImportableConfig]]) -> type[_ImportList]:
    """Define a mixin that adds ``fields`` into the config model.

    Parameters
    ----------
    fields: collections.abc.Mapping[str, type[ImportableConfig]]
        A mapping of field names to subclass of `ImportableConfig` to be included in
        the concrete class.

    Returns
    -------
    type['_ImportList']
        A concrete type.

    Examples
    --------
    The following: ::

        class A(ImportableConfig): pass

        class B(ImportListMixin({"a": A})): pass

    Equates to: ::

        class A:
            type: ImportString

        class B:
            __importable_fields_map__ = { "a": A }
            a: A
    """
    model = create_model(
        f"_{'_'.join(fields.keys())}",
        __base__=(_ImportList,),
        __doc__=None,
        __config__=None,
        __module__=__name__,
        __validators__=None,
        __cls_kwargs__=None,
        **{
            k: (
                Sequence[v],
                Field(default_factory=list),
            )
            for k, v in fields.items()
        },
    )
    model.__importable_fields_map__ = fields
    return model


class ConfigManager:
    RENDERED_CONFIG_KEY: ClassVar[Literal["__RenderedConfig__"]] = "__RenderedConfig__"

    _models: ClassVar[MutableMapping[str, Sequence[type[AutoLoadConfig]]]] = dict()
    config: ClassVar[Any]

    @classmethod
    def _add(cls, kls: type[AutoLoadConfig]) -> None:
        """Register a configuration model.

        Parameters
        ----------
        key : str
            Root key in the environment model.

        kls : type[~`pydantic.BaseModel`]:
            The configuration model.
        """
        if (
            kls not in cls._models.get(kls.__config_prefix__, tuple())
            and cls.RENDERED_CONFIG_KEY not in kls.__name__
        ):
            cls._models.update(
                {
                    kls.__config_prefix__: (
                        *cls._models.get(kls.__config_prefix__, tuple()),
                        kls,
                    )
                }
            )
            _keys = [kls.__config_prefix__] if kls.__config_prefix__ else []
            cls._eval_nested_imports(kls, *_keys)

    @classmethod
    def _eval_nested_imports(cls, kls: type[BaseModel], *keys: str) -> None:
        """Collect all importable types.

        Crawl through current model for all additional imports via
        ``pydantic.typing.ImportString`` model fields. This is called recursively, so
        circular import issues may exist, and worked around via the deferred list.

        Parameters
        ----------
        kls : type[`pydantic.BaseModel`]
            A type to crawl through and check if it requires any imports and/or nested
            imports.
        *keys : str
            A list of keys.
        """
        filtered_imports = (
            (key, field)
            for key, field in kls.model_fields.items()
            if _isimportable(field.annotation)
        )
        for key, field in filtered_imports:
            try:
                create_model(
                    "_temp",
                    __base__=(
                        _Config,
                        _construct_intermediary(
                            field,
                            *keys,
                            key,
                        ),
                    ),
                    __doc__=None,
                    __config__=None,
                    __module__=kls.__module__,
                    __validators__=None,
                    __cls_kwargs__=None,
                )()
            except ValidationError:
                pass

        filtered_nested = (
            (key, field.annotation)
            for key, field in kls.model_fields.items()
            if isinstance(field.annotation, type)
            and issubclass(field.annotation, BaseModel)
        )
        for key, field in filtered_nested:
            cls._eval_nested_imports(
                field,
                *keys,
                key,
            )

    @classmethod
    def reload(cls) -> Any:
        """Render and cache the final config.

        Reload the configuration from environment variables. Must be called at least
        once to load the variables into `.ConfigManager.config`.

        Returns
        -------
        ~`typing.Any`
            A instantiated configuration object. Cached to `/ConfigManager.config`.

        Raises
        ------
        ~`pydantic.ValidationError`
            If the configuration set was not loaded and/or verified.
        """
        props = dict()
        bases: Sequence[type[BaseModel]] = list([_Config])
        for key, models in cls._models.items():
            for model in models:
                if issubclass(model, _ImportList):
                    # Fully create the discriminated list
                    model._realize()
            if not key or not len(key):
                # Should be in root model
                bases.extend(models)
            else:
                # Has it's own root key
                props.update(
                    {
                        key: create_model(
                            f"{cls.RENDERED_CONFIG_KEY}{key}",
                            __base__=tuple(models),
                        )
                    }
                )

        cls.model = create_model(
            cls.RENDERED_CONFIG_KEY,
            __base__=tuple(bases),
            __doc__=None,
            __config__=None,
            __module__=__name__,
            __validators__=None,
            __cls_kwargs__=None,
            **{
                key: (_type, Field(default_factory=_type))
                for key, _type in props.items()
            },
        )

        try:
            cls.config = cls.model()
        except ValidationError:
            raise
        return cls.config
