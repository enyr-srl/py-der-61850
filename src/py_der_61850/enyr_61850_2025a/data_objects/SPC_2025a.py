from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from datetime import datetime
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.CtlModelKind_2025a import CtlModelKind_2025a


class SPC_2025a(DOType):
    """Abstract type, holding attributes common to analogue settings."""

    def __init__(
        self,
    ) -> None:
        # This common data class shall be used to represent single point controls with or without associated status information.
        self.stVal: bool = False

        self.q: Quality_2025a = Quality_2025a()  # Quality of the value in 'mxVal
        self.t: datetime | None = (
            None  # Timestamp of the last change or update event of 'mxVal' or the last change of value in 'q'
        )

        self.ctlModel: CtlModelKind_2025a = CtlModelKind_2025a.direct_normal 
        self.opRcvd: bool = (
            False  # True indicates that an 'operate' command for a controllable data object has been received
        )
        self.opOk: bool = (
            False  # True indicates that an operate command for a controllable data object has been evaluated and accepted.
        )
        self.t0pOk: datetime | None = None # The timestamp when 'opOk' becomes true, i.e., the timestamp when an output of a control object would be activated following an evaluated and accepted command.
        self.dchg : bool = False  #  Indicates that a data change reporting is requested when the value of 'stVal' changes significantly.

    def Operate(self,ctlVal: bool, Test = False) -> bool:
        """Operate command for controllable analogue process value or setpoint.

        Args:
            ctlVal (float): Service parameter that determines the control activity.
            Test: Se è un comando di test
        """

        # 1. Ingresso nello stato 'PerformTest' (Macchina a stati 7-2)
        # L'azione di ingresso è "set opRcvd" [13]
        self.opRcvd = True # per tracciamento

        try:
            # 2. Verifiche Operative (Operative Tests)
            # Verifica se il modello di controllo permette l'operazione [14]
            if self.ctlModel == CtlModelKind_2025a.status_only:
                # Fallimento: opOk non viene settato
                return False
            
            # Qui andrebbero inseriti controlli su Loc/Rem, Interblocchi, Range
            # Es: if ctlVal > self.maxVal: return False

            # 3. Esecuzione (Action)
            # Se i test passano, si applica il valore.
            stVal_old = self.stVal
            
            # Aggiornamento del valore (simulazione dell'azione fisica)
            self.stVal = ctlVal
            self.t = datetime.now()
            
            # 4. Aggiornamento Control Mirror (Feedback positivo)
            # opOk diventa True quando il comando è accettato [8]
            self.opOk = True
            self.t0pOk = self.t

            # 5. Valutazione del Trigger per Reporting (dchg)
            # Calcolo della soglia assoluta basata su db (unità 0.001%) e dbRef [5], [15]
            # Soglia = dbRef * (db / 100000)
            
            if self.stVal != stVal_old:
                # Il valore è cambiato abbastanza da giustificare un evento
                self._trigger_report_dchg()
            return True

        finally:
            # 6. Uscita dallo stato 'PerformTest'
            # L'azione di uscita è "reset opRcvd" [13].
            # Questo deve avvenire SEMPRE, sia in caso di successo che di errore.
            self.opRcvd = False

    def _trigger_report_dchg(self):
        """
        Questo metodo simula la notifica interna al Report Control Block.
        Nella realtà, qui chiameresti un callback o un observer.
        """
        self.dchg = True  #  Indicates that a data change reporting is requested when the value of 'stVal' changes significantly.

