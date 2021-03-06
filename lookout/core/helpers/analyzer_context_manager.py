from argparse import Namespace
import subprocess
from typing import Optional, Type

from lookout.core.analyzer import Analyzer
from lookout.core.cmdline import create_model_repo_from_args
from lookout.core.data_requests import DataService
from lookout.core.event_listener import EventListener
from lookout.core.helpers.server import check_port_free, find_port, LookoutSDK
from lookout.core.manager import AnalyzerManager


class AnalyzerContextManager:
    """Context manager for launching analyzer."""

    def __init__(self, analyzer: Type[Analyzer], db: str, fs: str,
                 init: bool = True, data_request_address: str = "localhost:10301"):
        """
        Initialization.

        :param db: path to an SQLite database with model metadata.
        :param fs: location where to store the trained model.
        :param analyzer: analyzer class to use.
        :param init: Value indicating whether to run the destructive database initialization \
                     or not. If you want to reuse an existing database set False.
        :param data_request_address: DataService GRPC endpoint to use.
        """
        self.analyzer = analyzer
        self.init = init
        self._port = find_port()
        self.data_request_address = data_request_address
        self._sql_alchemy_model_args = Namespace(
            db="sqlite:///%s" % db,
            fs=fs,
            cache_size="1G",
            cache_ttl="6h",
            db_kwargs={},
        )
        self._lookout_sdk = None

    def __enter__(self) -> "AnalyzerContextManager":
        """
        Create the context and run the events listener.
        """
        self.model_repository = create_model_repo_from_args(self._sql_alchemy_model_args)
        if self.init:
            self.model_repository.init()
        self.data_service = DataService(self.data_request_address)
        self.manager = AnalyzerManager(analyzers=[self.analyzer],
                                       model_repository=self.model_repository,
                                       data_service=self.data_service)
        if not check_port_free(self._port):
            self._port = find_port()
        self.listener = EventListener(address="0.0.0.0:%d" % self._port, handlers=self.manager,
                                      n_workers=1)
        self.listener.start()
        self._lookout_sdk = LookoutSDK()
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        """
        Stop the events listener and shutdown the context.
        """
        self._lookout_sdk = None
        self.listener.stop()
        self.model_repository.shutdown()
        self.data_service.shutdown()

    def review(self, fr: str, to: str, *, git_dir: str, bblfsh: Optional[str]=None,
               log_level: Optional[str]=None, config_json: Optional[dict]=None) \
            -> subprocess.CompletedProcess:
        """
        Proxy for LookoutSDK.review().

        Triggers a review event and effectively calls the underlying analyzer's `analyze()`.
        Read parameters description in `LookoutSDK.review()`
        """
        if not self._lookout_sdk:
            raise AttributeError(
                "AnalyzerContextManager.review() is available only inside `with`")
        return self._lookout_sdk.review(fr, to, self._port, git_dir=git_dir, bblfsh=bblfsh,
                                        log_level=log_level, config_json=config_json)

    def push(self, fr: str, to: str, *, git_dir: str, bblfsh: Optional[str]=None,
             log_level: Optional[str]=None, config_json: Optional[dict]=None) \
            -> subprocess.CompletedProcess:
        """
        Proxy for LookoutSDK.push().

        Triggers a push event and effectively calls the underlying analyzer's `train()`.
        Read parameters description in `LookoutSDK.push()`
        """
        if not self._lookout_sdk:
            raise AttributeError(
                "AnalyzerContextManager.push() is available only inside `with` statement")
        return self._lookout_sdk.push(fr, to, self._port, git_dir=git_dir, bblfsh=bblfsh,
                                      log_level=log_level, config_json=config_json)
