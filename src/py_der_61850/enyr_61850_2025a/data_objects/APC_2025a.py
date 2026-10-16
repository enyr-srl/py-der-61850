from datetime import datetime

from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.CtlModelKind_2025a import CtlModelKind_2025a
from py_der_61850.enyr_61850_2025a.data_objects.data_object_type import DOType
from py_der_61850.enyr_61850_2025a.data_objects.Quality_2025a import Quality_2025a
from py_der_61850.enyr_61850_2025a.data_attribute_enumerations.ValidityKind_2025a import ValidityKind_2025a


class APC_2025a(DOType):
    def __init__(
        self,
    ) -> None:
        
        # Measured attributes
        self.mxVal: float = 0.0  # 	Current value of the controllable analogue process value or of the setpoint
        self.q: Quality_2025a = Quality_2025a()  # Quality of the value in 'mxVal
        self.t: datetime | None = (
            None  # Timestamp of the last change or update event of 'mxVal' or the last change of value in 'q'
        )

        # Deadband configuration 
        # db è un intero che rappresenta unità di 0.001%. 
        # Es: 1000 = 1.000%, 500 = 0.500%
        self.db: int = 1000  
        
        # dbRef è MANDATORIO per APC [6]. Rappresenta il valore di riferimento (fondo scala)
        # su cui calcolare la percentuale del deadband.
        self.dbRef: float = 100.0 

        # Substitution
        self.subEna: bool = False  #  Used to enable and disable substitution
        self.subVal: float = 0.0  # Value used to substitute 'mxVal'.
        self.subQ: Quality_2025a = Quality_2025a()  # Value used to substitute 'q'

        # Control mirror and services
        self.dchg: bool = False  #  Indicates that a data change reporting is requested when the value of 'mxVal' changes significantly.
        self.ctlModel: CtlModelKind_2025a = CtlModelKind_2025a.direct_normal 
        self.opRcvd: bool = (
            False  # True indicates that an 'operate' command for a controllable data object has been received
        )
        self.opOk: bool = (
            False  # True indicates that an operate command for a controllable data object has been evaluated and accepted.
        )
        self.t0pOk: datetime | None = None # The timestamp when 'opOk' becomes true, i.e., the timestamp when an output of a control object would be activated following an evaluated and accepted command.

    def Operate(self,ctlVal: float, Test = False) -> bool:
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
            mxVal_old = self.mxVal
            
            # Aggiornamento del valore (simulazione dell'azione fisica)
            self.mxVal = ctlVal
            self.t = datetime.now()
            
            # 4. Aggiornamento Control Mirror (Feedback positivo)
            # opOk diventa True quando il comando è accettato [8]
            self.opOk = True
            self.t0pOk = self.t

            # 5. Valutazione del Trigger per Reporting (dchg)
            # Calcolo della soglia assoluta basata su db (unità 0.001%) e dbRef [5], [15]
            # Soglia = dbRef * (db / 100000)
            threshold = self.dbRef * (self.db / 100000.0)
            delta = abs(self.mxVal - mxVal_old)
            
            if delta > threshold:
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
        self.dchg: bool = True  #  Indicates that a data change reporting is requested when the value of 'mxVal' changes significantly.


        
        

    

