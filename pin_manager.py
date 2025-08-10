import sqlite3
import logging
from datetime import datetime
import random
import string
from inefable_api_client import get_inefable_client

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PinManager:
    """Gestor de pines que maneja stock local y API externa como respaldo"""
    
    def __init__(self, database_path):
        self.database_path = database_path
        self.inefable_client = get_inefable_client()
        
    def get_db_connection(self):
        """Obtiene una conexión a la base de datos"""
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_local_stock(self, monto_id=None):
        """Obtiene el stock local de pines"""
        conn = self.get_db_connection()
        
        if monto_id:
            # Stock para un monto específico
            count = conn.execute('''
                SELECT COUNT(*) FROM pines_freefire 
                WHERE monto_id = ? AND usado = FALSE
            ''', (monto_id,)).fetchone()[0]
            conn.close()
            return count
        else:
            # Stock para todos los montos
            stock = {}
            for i in range(1, 10):
                count = conn.execute('''
                    SELECT COUNT(*) FROM pines_freefire 
                    WHERE monto_id = ? AND usado = FALSE
                ''', (i,)).fetchone()[0]
                stock[i] = count
            conn.close()
            return stock
    
    def get_local_pin(self, monto_id):
        """Obtiene un pin del stock local"""
        conn = self.get_db_connection()
        pin = conn.execute('''
            SELECT * FROM pines_freefire 
            WHERE monto_id = ? AND usado = FALSE 
            LIMIT 1
        ''', (monto_id,)).fetchone()
        conn.close()
        return pin
    
    def remove_local_pin(self, pin_id):
        """Elimina un pin del stock local"""
        conn = self.get_db_connection()
        conn.execute('DELETE FROM pines_freefire WHERE id = ?', (pin_id,))
        conn.commit()
        conn.close()
    
    def add_local_pin(self, monto_id, pin_code, source='manual'):
        """Añade un pin al stock local"""
        conn = self.get_db_connection()
        try:
            # Verificar si el pin ya existe
            existing = conn.execute('''
                SELECT id FROM pines_freefire 
                WHERE pin_codigo = ? AND monto_id = ?
            ''', (pin_code, monto_id)).fetchone()
            
            if existing:
                conn.close()
                return False, "Pin ya existe en el stock"
            
            # Agregar pin
            conn.execute('''
                INSERT INTO pines_freefire (monto_id, pin_codigo)
                VALUES (?, ?)
            ''', (monto_id, pin_code))
            conn.commit()
            conn.close()
            
            logger.info(f"Pin agregado al stock local - Monto: {monto_id}, Source: {source}")
            return True, "Pin agregado exitosamente"
            
        except Exception as e:
            conn.rollback()
            conn.close()
            logger.error(f"Error al agregar pin local: {str(e)}")
            return False, f"Error al agregar pin: {str(e)}"
    
    def request_pin_with_fallback(self, monto_id, use_external_api=True):
        """
        Solicita un pin con sistema de respaldo:
        1. Primero intenta obtener del stock local
        2. Si no hay stock local y use_external_api=True, usa la API externa
        
        Args:
            monto_id (int): ID del monto (1-9)
            use_external_api (bool): Si usar API externa como respaldo
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            logger.info(f"Solicitando pin para monto_id {monto_id}")
            
            # 1. Intentar obtener pin del stock local
            local_stock = self.get_local_stock(monto_id)
            logger.info(f"Stock local para monto {monto_id}: {local_stock}")
            
            if local_stock > 0:
                # Hay stock local disponible
                local_pin = self.get_local_pin(monto_id)
                if local_pin:
                    # Eliminar pin del stock local
                    self.remove_local_pin(local_pin['id'])
                    
                    logger.info(f"Pin obtenido del stock local - Monto: {monto_id}")
                    return {
                        'status': 'success',
                        'pin_code': local_pin['pin_codigo'],
                        'monto_id': monto_id,
                        'source': 'local_stock',
                        'timestamp': datetime.now().isoformat(),
                        'stock_remaining': local_stock - 1
                    }
            
            # 2. Si no hay stock local, usar API externa como respaldo
            if use_external_api:
                logger.info(f"Stock local agotado para monto {monto_id}, usando API externa")
                
                # Verificar si la API externa está disponible
                if not self.inefable_client.is_available():
                    return {
                        'status': 'error',
                        'message': 'Stock local agotado y API externa no disponible',
                        'error_type': 'no_stock_no_api',
                        'local_stock': local_stock
                    }
                
                # Solicitar pin a la API externa
                external_result = self.inefable_client.request_pin(monto_id)
                
                if external_result.get('status') == 'success':
                    logger.info(f"Pin obtenido de API externa - Monto: {monto_id}")
                    
                    # Opcionalmente, agregar el pin obtenido al stock local para futuras consultas
                    pin_code = external_result.get('pin_code')
                    if pin_code:
                        # Agregar al stock local con marca de origen externo
                        self.add_local_pin(monto_id, pin_code, source='inefable_api')
                    
                    return {
                        'status': 'success',
                        'pin_code': pin_code,
                        'monto_id': monto_id,
                        'source': 'inefable_api',
                        'timestamp': datetime.now().isoformat(),
                        'local_stock': local_stock,
                        'external_response': external_result
                    }
                else:
                    logger.error(f"Error en API externa: {external_result.get('message', 'Error desconocido')}")
                    return {
                        'status': 'error',
                        'message': f"Stock local agotado y error en API externa: {external_result.get('message', 'Error desconocido')}",
                        'error_type': 'external_api_error',
                        'local_stock': local_stock,
                        'external_error': external_result
                    }
            else:
                # No usar API externa
                return {
                    'status': 'error',
                    'message': 'Stock local agotado',
                    'error_type': 'no_local_stock',
                    'local_stock': local_stock
                }
                
        except Exception as e:
            logger.error(f"Error inesperado al solicitar pin: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error inesperado: {str(e)}',
                'error_type': 'unexpected'
            }
    
    def request_multiple_pins(self, monto_id, cantidad, use_external_api=True):
        """
        Solicita múltiples pines con sistema de respaldo
        
        Args:
            monto_id (int): ID del monto (1-9)
            cantidad (int): Cantidad de pines solicitados
            use_external_api (bool): Si usar API externa como respaldo
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            logger.info(f"Solicitando {cantidad} pines para monto_id {monto_id}")
            
            if cantidad <= 0:
                return {
                    'status': 'error',
                    'message': 'La cantidad debe ser mayor a 0',
                    'error_type': 'validation'
                }
            
            pines_obtenidos = []
            local_stock = self.get_local_stock(monto_id)
            pines_desde_local = min(cantidad, local_stock)
            pines_desde_externa = cantidad - pines_desde_local
            
            logger.info(f"Plan: {pines_desde_local} del stock local, {pines_desde_externa} de API externa")
            
            # 1. Obtener pines del stock local
            for i in range(pines_desde_local):
                local_pin = self.get_local_pin(monto_id)
                if local_pin:
                    self.remove_local_pin(local_pin['id'])
                    pines_obtenidos.append({
                        'pin_code': local_pin['pin_codigo'],
                        'source': 'local_stock'
                    })
                else:
                    logger.warning(f"Pin local esperado no encontrado en iteración {i+1}")
                    break
            
            # 2. Obtener pines restantes de la API externa
            if pines_desde_externa > 0 and use_external_api:
                if not self.inefable_client.is_available():
                    logger.warning("API externa no disponible para pines restantes")
                else:
                    for i in range(pines_desde_externa):
                        external_result = self.inefable_client.request_pin(monto_id)
                        
                        if external_result.get('status') == 'success':
                            pin_code = external_result.get('pin_code')
                            if pin_code:
                                pines_obtenidos.append({
                                    'pin_code': pin_code,
                                    'source': 'inefable_api'
                                })
                                
                                # Agregar al stock local para futuras consultas
                                self.add_local_pin(monto_id, pin_code, source='inefable_api')
                        else:
                            logger.error(f"Error en API externa para pin {i+1}: {external_result.get('message')}")
                            break
            
            # Resultado final
            if len(pines_obtenidos) == cantidad:
                return {
                    'status': 'success',
                    'pins': pines_obtenidos,
                    'cantidad_solicitada': cantidad,
                    'cantidad_obtenida': len(pines_obtenidos),
                    'monto_id': monto_id,
                    'timestamp': datetime.now().isoformat(),
                    'sources_used': list(set([pin['source'] for pin in pines_obtenidos]))
                }
            elif len(pines_obtenidos) > 0:
                return {
                    'status': 'partial_success',
                    'pins': pines_obtenidos,
                    'cantidad_solicitada': cantidad,
                    'cantidad_obtenida': len(pines_obtenidos),
                    'monto_id': monto_id,
                    'timestamp': datetime.now().isoformat(),
                    'message': f'Solo se pudieron obtener {len(pines_obtenidos)} de {cantidad} pines solicitados',
                    'sources_used': list(set([pin['source'] for pin in pines_obtenidos]))
                }
            else:
                return {
                    'status': 'error',
                    'message': 'No se pudieron obtener pines',
                    'error_type': 'no_pins_available',
                    'cantidad_solicitada': cantidad,
                    'local_stock': local_stock
                }
                
        except Exception as e:
            logger.error(f"Error inesperado al solicitar múltiples pines: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error inesperado: {str(e)}',
                'error_type': 'unexpected'
            }
    
    def get_stock_status(self):
        """Obtiene el estado completo del stock (local + API externa)"""
        try:
            local_stock = self.get_local_stock()
            api_available = self.inefable_client.is_available()
            
            # Intentar obtener información de saldo de la API externa
            api_balance = None
            if api_available:
                balance_result = self.inefable_client.get_balance()
                if balance_result.get('status') == 'success':
                    api_balance = balance_result
            
            return {
                'status': 'success',
                'local_stock': local_stock,
                'total_local_pins': sum(local_stock.values()),
                'external_api': {
                    'available': api_available,
                    'balance_info': api_balance
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error al obtener estado del stock: {str(e)}")
            return {
                'status': 'error',
                'message': f'Error al obtener estado: {str(e)}',
                'error_type': 'status_error'
            }
    
    def test_external_api(self):
        """Prueba la conexión con la API externa"""
        try:
            success, message = self.inefable_client.test_connection()
            return {
                'status': 'success' if success else 'error',
                'message': message,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error al probar API externa: {str(e)}',
                'error_type': 'test_error'
            }

    def check_combined_stock(self, monto_id):
        """
        Verifica el stock combinado (local + API externa) para un monto específico
        
        Args:
            monto_id (int): ID del monto (1-9)
            
        Returns:
            dict: Estado del stock combinado
        """
        try:
            # Stock local
            local_stock = self.get_local_stock(monto_id)
            
            # Verificar API externa
            external_available = False
            external_message = "API externa no disponible"
            
            if self.inefable_client.is_available():
                # Verificar stock específico en API externa
                stock_check = self.inefable_client.check_stock_availability(monto_id)
                external_available = stock_check.get('available', False)
                external_message = stock_check.get('message', 'Estado desconocido')
            
            # Determinar disponibilidad total
            total_available = local_stock > 0 or external_available
            
            return {
                'status': 'success',
                'monto_id': monto_id,
                'local_stock': local_stock,
                'external_available': external_available,
                'external_message': external_message,
                'total_available': total_available,
                'message': self._get_stock_message(local_stock, external_available),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error al verificar stock combinado para monto {monto_id}: {str(e)}")
            return {
                'status': 'error',
                'monto_id': monto_id,
                'total_available': False,
                'message': f'Error al verificar stock: {str(e)}',
                'error_type': 'check_error'
            }
    
    def _get_stock_message(self, local_stock, external_available):
        """Genera mensaje descriptivo del estado del stock"""
        if local_stock > 0 and external_available:
            return f"Stock disponible ({local_stock} local + API externa)"
        elif local_stock > 0:
            return f"Stock local disponible ({local_stock})"
        elif external_available:
            return "Disponible vía API externa"
        else:
            return "Sin stock disponible"

def create_pin_manager(database_path):
    """Crea una instancia del gestor de pines"""
    return PinManager(database_path)
